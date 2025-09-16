import asyncio
from typing import Optional
from contextlib import AsyncExitStack
from datetime import datetime
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from dotenv import load_dotenv
import os
import logging
import json
from openai import NOT_GIVEN, OpenAI
from openai.types.model import Model
from mcp.types import Tool, CallToolResult
from typing import Literal
from openai.types.responses import ResponseFunctionToolCall

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))  # load environment variables from .env

logs_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(logs_dir, exist_ok=True)

# 生成日志文件名（按日期）
today = datetime.now().strftime("%Y-%m-%d")
log_file = os.path.join(logs_dir, f"lw_orch_client.log")
# 配置根日志记录器
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
    ]
)

# 配置httpx日志级别为INFO，让它输出到我们的日志文件
httpx_logger = logging.getLogger("httpx")
httpx_logger.setLevel(logging.INFO)
# 配置FastMCP相关的日志
mcp_logger = logging.getLogger("mcp")
mcp_logger.setLevel(logging.INFO)

logger = logging.getLogger(__name__)

class MCPClient:
    def __init__(self):
        # Initialize session and client objects
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.openai = OpenAI(base_url=os.environ.get("LW_OPENAI_BASE_URL"),
                             api_key=os.environ.get("LW_API_KEY"))
        
    def get_models(self) -> list[Model]:
        """Get the models available from the OpenAI API"""
        response = self.openai.models.list()
        return response.data
    
    async def get_prompts(self) -> list[str]:
        """Get the prompts available from the MCP server"""
        response = await self.session.list_prompts()
        return response.prompts
    
    async def connect_to_server(self, server_url: str):
        """Connect to an MCP server via streamable HTTP

        Args:
            server_url: URL of the MCP server (e.g., 'http://localhost:3000/mcp')
        """
        # Create streamable HTTP client connection
        read_stream, write_stream, _ = await self.exit_stack.enter_async_context(streamablehttp_client(server_url))
        
        # Create client session
        self.session = await self.exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )

        await self.session.initialize()
        logger.info("Connected to the MCP server now!")
        
        self.tools = await self.get_tools()
        logger.info("Already retrieve the tools from the MCP server!")
        
        self.prompts = await self.get_prompts()
        logger.info("Already retrieve the prompts from the MCP server!")
        
    async def get_tools(self) -> list[Tool]:
        """Get the tools available from the MCP server"""
        response = await self.session.list_tools()
        return response.tools
    
    async def process_query(self, 
                            query: str | None,
                            instructions: str,
                            messages: list[dict]) -> tuple[list[str], list[dict], bool]:
        """Process a query using OpenAI and available tools"""
        available_tools = self.convert2openai_tool(self.tools)

        # send a openai api call
        if query is not None:
            messages.append({
                "role": "user",
                "content": query
            })
        response = self.make_request2openai(messages, instructions, available_tools, "gpt-4.1")

        # Process response and handle tool calls
        final_text = []
        has_tool_calls = False

        assistant_message_content = []
        for content in response.output:
            if content.type == "message":
                output_text = self.parse_openai_message(content.content)
                final_text.append(output_text)
                # 无需为模型的message类型输出专门去转换成下一轮对话的输入，输出格式和input item一致
                assistant_message_content.append(content)
            elif content.type == 'function_call':
                has_tool_calls = True
                tool_name, tool_args = self.parse_openai_function_call(content)

                # Execute tool call
                try:
                    mcp_result = await self.session.call_tool(tool_name, tool_args)
                    final_text.append(f"正在调用工具 {tool_name}，参数: {tool_args}")
                    logger.info(f"Calling tool {tool_name} with args {tool_args} -> \n{mcp_result.structuredContent}")

                    function_call_output = self.convert2openai_function_call_output(content, mcp_result)
                    assistant_message_content.append(content)
                    assistant_message_content.append(function_call_output)
                except Exception as e:
                    logger.error(f"Tool call failed: {e}")
                    final_text.append(f"工具调用失败: {e}")
                    # 创建错误响应
                    error_output = {
                        "type": "function_call_output",
                        "call_id": content.call_id,
                        "output": json.dumps({"error": str(e)})
                    }
                    assistant_message_content.append(content)
                    assistant_message_content.append(error_output)

        return final_text, messages + assistant_message_content, has_tool_calls
    
    async def chat(self):
        """Run an interactive chat loop"""
        print("\033[1;30;47m我是LightWAN Orch Server智能查询小助手（MCP Client版本）!\033[0m")
        print("\033[1;30;47m我假设你的Server地址是http://10.30.68.19，接下来请你先提供你的client_id和client_secret，不然没法正常工作喔.\033[0m")
        self.client_id = input("\033[1;30;47m请输入你的client_id: \033[0m")
        self.client_secret = input("\033[1;30;47m请输入你的client_secret: \033[0m")
        auth_result = (await self.session.call_tool(
            "get_access_token", 
            {"client_id": self.client_id, "client_secret": self.client_secret})).structuredContent
        self.access_token, self.scope = auth_result.get("access_token", None), auth_result.get("scope", None)
        # system prompt
        instructions = (await self.session.get_prompt(
            "initial_instruction", 
            {"access_token": self.access_token, "scope": self.scope})).messages[0].content.text
        
        messages = []
        while True:
            try:
                query = input("\033[1;30;47m \nQuery: \033[0m").strip()

                if query.lower() == 'quit':
                    break

                # 处理用户查询，可能需要多轮工具调用
                max_try = 5  # 最大重试次数
                current_try = 0
                
                while current_try < max_try:
                    output_text, messages, has_tool_calls = await self.process_query(query, instructions, messages)
                    
                    if has_tool_calls:
                        # 有工具调用，显示工具调用信息但不等待用户输入
                        print("\033[1;31m" + '\n'.join(output_text) + "\033[0m")
                        current_try += 1
                        query = ""  # 清空query，下一轮不需要用户输入
                    else:
                        # 没有工具调用，显示最终结果并跳出循环
                        print("\033[1;32m" + '\n'.join(output_text) + "\033[0m")
                        break
                
                if current_try >= max_try:
                    print(f"\033[1;31;41m工具调用次数超过{max_try}次，请重新开始对话。\033[0m")

            except Exception as e:
                print(e)
    
    def make_request2openai(self, 
                            messages: list[dict],
                            system_prompt: str,
                            tools: list[Tool] | None = None,
                            model: str="gpt-4.1") -> str:
        """Make a request to the OpenAI API"""
        params = {
            "model": model,
            "input": messages,
            "instructions": system_prompt,
            "tools": tools,
        }
        response = self.openai.responses.create(**params)
        return response
    
    def convert2openai_tool(self, tools: list[Tool]) -> dict:
        """Convert a MCP tool list to an OpenAI tool list"""
        available_tools = [{
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": {
                "type": "object",
                "properties": tool.inputSchema["properties"]
            }
        } for tool in tools]
        return available_tools
    
    def parse_openai_message(self, content: list) -> str:
        """ parse the openai text response 
        无需为模型的message类型输出专门去转换成下一轮对话的输入，输出格式和input item一致
        """
        results = ""
        for item in content:
            results += item.text
        
        return results
        
    def parse_openai_function_call(self, content: list) -> str:
        """ parse the openai function call response """
        tool_name = content.name
        tool_args = json.loads(content.arguments)
        
        return tool_name, tool_args
    
    def convert2openai_function_call_output(self, 
                                            content: ResponseFunctionToolCall,
                                            mcp_result: CallToolResult) -> dict:
        """ convert the openai function call output to an input item for next round """
        result = mcp_result.structuredContent if mcp_result.structuredContent is not None else mcp_result.content
        return {
            "type": "function_call_output",
            "call_id": content.call_id,
            "output": json.dumps(result)
        }
        
    async def __aenter__(self):
        """Async context manager entry"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        self.session = None
        await self.exit_stack.aclose()
        
async def main():
    async with MCPClient() as client:
        await client.connect_to_server("http://localhost:8000/mcp")
        await client.chat()
    
if __name__ == "__main__":
    asyncio.run(main())