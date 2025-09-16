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
        {'access_token': ..., 'token_type': ..., 'expires_in': 'how many seconds the token will be expired!', 'scope': 'authorized operation list for this token'}
    """
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/oauth/token", 
            data={"client_id": client_id, "client_secret": client_secret, "grant_type": grant_type},
        )
    
    return response.json()

@mcp.tool() 
def authenticate(scope: list[str]) -> str:
    """Authenticate the user with the given scope. Because the global and customer token have different endpoints for future tools.
    
    Args:
        scope: authorized operation list for this token. It should be the result of `get_access_token` tool.
        
    Returns:
        a fixed value between [global, customer]
    """
    # TODO: 目前是一种快速的做法，如果scope中包含global，则返回global，否则返回customer。但是否是这样的逻辑仍有待确定。
    if any(scope.startswith("global") for scope in scope):
        return "global"
    else:
        return "customer"
    
async def get_all_sites_info(access_token: str, customer_id: str|None = None, page: int|None = None, size: int = 20) -> dict[str, Any]:
    """Get all sites info for a given customer id. This is a paginated query interface where you can control the page number and page size.
    
    Args:
        access_token: access token
        customer_id: customer id
        page: page number, default is None, which means all sites will be returned
        size: page size
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    result = {
        "total_pages": 0,
        "total_elements": 0,
        "content": [],
    }
    async with httpx.AsyncClient() as client:
        if page is None:
            # 全量查询：循环获取所有页面
            all_sites = []
            current_page = 0
            total_pages = None
            
            while True:
                response = await client.get(
                    f"{BASE_URL}/openapi/v2/sites",
                    params={"page": current_page, "size": size},
                    headers=headers
                )
                
                data = response.json()
                sites = data.get("content", [])
                all_sites.extend(sites)
                total_pages = data.get("total_pages", 0)
                if current_page >= total_pages:
                    break # break the loop if all pages have been queried
                    
                current_page += 1
            
            result["total_pages"] = total_pages
            result["total_elements"] = data.get("total_elements", 0)
            result["content"] = all_sites
            
            return result
        else:
            response = await client.get(
                f"{BASE_URL}/openapi/v2/sites",
                params={"page": page, "size": size},
                headers=headers
            )
            
            data = response.json()
            result["total_pages"] = data.get("total_pages", 0)
            result["total_elements"] = data.get("total_elements", 0)
            result["content"] = data.get("content", [])
            
            return result

if __name__ == "__main__":
    # Initialize and run the server
    print(BASE_URL)
    asyncio.run(get_access_token("ec515f8a95c5490cbb746033c822fe21", 
                                 "2e29341f59a732a4969b569ab0e533218701e755"))
    # mcp.run(transport='streamable-http')