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
from openai import OpenAI
from openai.types.model import Model
from mcp.types import Tool

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))  # load environment variables from .env

logs_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(logs_dir, exist_ok=True)

# 生成日志文件名（按日期）
today = datetime.now().strftime("%Y-%m-%d")
log_file = os.path.join(logs_dir, f"client.log")
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
        
    async def get_tools(self) -> list[Tool]:
        """Get the tools available from the MCP server"""
        response = await self.session.list_tools()
        return response.tools
    
    async def process_query(self, query: str) -> str:
        """Process a query using OpenAI and available tools"""

        available_tools = [{
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": {
                "type": "object",
                "properties": tool.inputSchema["properties"]
            }
        } for tool in self.tools]
        
        # system prompt
        instructions = '''You are a Chinese weather assistant. You can use available tools to improve the accuracy of your response. 
        Finally, you should reply in Chinese in future.'''
        messages = [
            {
                "role": "user",
                "content": query
            }
        ]

        # send a openai api call
        response = self.openai.responses.create(
            model="gpt-4.1",
            input=messages,
            tools=available_tools,
            instructions=instructions
        )

        # Process response and handle tool calls
        final_text = []

        assistant_message_content = []
        for content in response.output:
            if content.type == "message":
                final_text.append(content.text)
                assistant_message_content.append(content)
            elif content.type == 'function_call':
                tool_name = content.name
                tool_args = json.loads(content.arguments)

                # Execute tool call
                result = await self.session.call_tool(tool_name, tool_args)
                final_text.append(f"[Calling tool {tool_name} with args {tool_args}]")
                logger.info(f"Calling tool {tool_name} and get -> \n{result.structuredContent}")

                assistant_message_content.append(content)
                messages += assistant_message_content
                
                messages.append({
                    "type": "function_call_output",
                    "call_id": content.call_id,
                    "output": json.dumps(
                        result.structuredContent
                    )
                })

        # Get next response from OpenAI
        response = self.openai.responses.create(
            model="gpt-4.1",
            input=messages,
            tools=available_tools,
            instructions=instructions
        )
        
        final_text = "\n".join(final_text)+response.output_text

        return final_text
    
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
        print(await client.process_query("今天杭州的天气怎么样？"))
    
if __name__ == "__main__":
    asyncio.run(main())