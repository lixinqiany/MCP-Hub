import asyncio
from typing import Optional
from contextlib import AsyncExitStack
from datetime import datetime
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
from dotenv import load_dotenv
import os
import logging

load_dotenv()  # load environment variables from .env

logs_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(logs_dir, exist_ok=True)

# 生成日志文件名（按日期）
today = datetime.now().strftime("%Y-%m-%d")
log_file = os.path.join(logs_dir, f"weather_server.log")
# 配置根日志记录器
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# 配置FastMCP相关的日志
mcp_logger = logging.getLogger("mcp")
mcp_logger.setLevel(logging.INFO)

logger = logging.getLogger(__name__)

class MCPClient:
    def __init__(self):
        # Initialize session and client objects
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
    
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
        
    async def get_tools(self):
        """Get the tools available from the MCP server"""
        response = await self.session.list_tools()
        tools = response.tools
        return tools
    
    async def close(self):
        """Properly close all resources"""
        if self.exit_stack:
            await self.exit_stack.__aexit__(None, None, None)
            self._connected = False
            self.session = None
    
    async def __aenter__(self):
        """Async context manager entry"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()
    
async def main():
    async with MCPClient() as client:
        await client.connect_to_server("http://localhost:8000/mcp")
        tools = await client.get_tools()
        print(tools)
    
if __name__ == "__main__":
    asyncio.run(main())