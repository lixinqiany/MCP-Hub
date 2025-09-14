import os, logging, httpx, asyncio
from datetime import datetime, timedelta
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv
from typing import Any

logs_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(logs_dir, exist_ok=True)

log_file = os.path.join(logs_dir, f"lw_orch_server.log")

# 配置根日志记录器
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler() # print into console
    ]
)

# 配置httpx日志级别为INFO，让它输出到我们的日志文件
httpx_logger = logging.getLogger("httpx")
httpx_logger.setLevel(logging.INFO)

# 配置FastMCP相关的日志
mcp_logger = logging.getLogger("mcp")
mcp_logger.setLevel(logging.INFO)

logger = logging.getLogger(__name__)
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))  # load environment variables from .env


# Initialize FastMCP server
mcp = FastMCP("lw_orch")

BASE_URL = os.environ.get("BASE_URL")

@mcp.tool()
def get_date_info(offset: int = 0) -> dict[str, Any]:
    """Get date information with optional offset from today
    
    Args:
        offset: Number of days offset from today (0=today, 1=tomorrow, -1=yesterday, etc.)
    """
    
    target_date = datetime.now() + timedelta(days=offset)
    
    # Get weekday information
    weekdays_english = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    weekday_english = weekdays_english[target_date.weekday()]
    
    # Format date based on format_type
    formatted_date = target_date.strftime("%Y年%m月%d日")
    
    return {
        "date": formatted_date,
        "weekday": weekday_english,
        "year": target_date.year,
        "month": target_date.month,
        "day": target_date.day,
        "timestamp": target_date.timestamp(),
    }

@mcp.tool()
async def get_access_token(client_id: str, 
                     client_secret: str, 
                     grant_type: str = "client_credentials") -> dict[str, Any]:
    """Get access token LightWAN Orch Server. 
    This access token is required parameter for other api calls.
    
    Args:
        client_id: client id (provided by user client)
        client_secret: client secret (provided by user client)
        grant_type: grant type, default is `client_credentials`
        
    Returns:
        {'access_token': ..., 'token_type': ..., 'expires_in': 'how many seconds the token will be expired!', 'scope': '...'}
    """
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/oauth/token", 
            data={"client_id": client_id, "client_secret": client_secret, "grant_type": grant_type},
        )
    
    return response.json()

if __name__ == "__main__":
    # Initialize and run the server
    print(BASE_URL)
    asyncio.run(get_access_token("ec515f8a95c5490cbb746033c822fe21", 
                                 "2e29341f59a732a4969b569ab0e533218701e755"))
    # mcp.run(transport='streamable-http')