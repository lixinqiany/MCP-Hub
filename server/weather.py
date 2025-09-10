from typing import Any
import httpx
import pandas as pd
import os
import logging
from datetime import datetime
from mcp.server.fastmcp import FastMCP
from exception.NotFound import NotFound
import asyncio

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

# 配置httpx日志级别为INFO，让它输出到我们的日志文件
httpx_logger = logging.getLogger("httpx")
httpx_logger.setLevel(logging.INFO)

# 配置FastMCP相关的日志
mcp_logger = logging.getLogger("mcp")
mcp_logger.setLevel(logging.INFO)

logger = logging.getLogger(__name__)

# Initialize FastMCP server
mcp = FastMCP("weather")

# Constants
API_BASE = "https://restapi.amap.com/v3/weather/weatherInfo"
API_KEY = "1239f8d61a0eafd9d7828251c11e04ad"
USER_AGENT = "weather-app/1.0"

# city2adcode
city2code_path = os.path.join(os.path.dirname(__file__), "AMap_adcode_citycode.xlsx")
city2code = pd.read_excel(city2code_path)

async def make_request(url: str, params: dict[str, Any]) -> dict[str, Any] | None:
    """Make a request to the 高德API with error handling."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json"
    }
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, timeout=30.0, params=params)
            response.raise_for_status()
            return response.json()
        except Exception:
            return None

@mcp.tool()
async def get_forecast(city: str) -> list[dict[str, Any]]:
    """Get weather forecast for a city in China. You should type in Chinese.

    Args:
        city: City name in Chinese. It supports Country, Province, City, District e.g. 浙江省, 杭州市, 萧山区...
    """
    
    try:
        adcode = get_adcode_by_city(city)
    except NotFound as e:
        return e.message

    forecast_params = {
        "key": API_KEY,
        "city": adcode,
        "extensions": "all", # all means forecasted info.
        "output": "JSON"
    }
    
    forecast_data = await make_request(API_BASE, forecast_params)

    if "forecasts" not in forecast_data or len(forecast_data["forecasts"]) == 0:
        # TODO: I am not sure how to judge if I get the forecast data. Waiting for such a case.
        return "There is no forecast data for this city"
    
    return forecast_data["forecasts"][0]['casts']

def get_adcode_by_city(city: str) -> str:
    """Get the adcode of a city in China.

    Args:
        city: City name in Chinese. It supports Country, Province, City, District e.g. 浙江省, 杭州市, 萧山区...
    """
    adcode = city2code[city2code["中文名"] == city]["adcode"]
    if adcode.empty:
        raise NotFound(f"City {city} not found in 高德 database. Maybe there is a typo, Or Maybe city name is not ending with 省/市/区.")
    return adcode.values[0]

@mcp.tool()
async def get_realtime_weather(city: str) -> dict[str, Any]:
    """Get realtime weather info. for a city in China.

    Args:
        city: City name in Chinese. It supports Country, Province, City, District e.g. 浙江省, 杭州市, 萧山区...
    """
    
    try:
        adcode = get_adcode_by_city(city)
        realtime_weather_params = {
            "key": API_KEY,
            "city": adcode,
            "extensions": "base", # base means realtime info.
            "output": "JSON"
        }
        realtime_weather_data = await make_request(API_BASE, realtime_weather_params)
    except NotFound as e:
        return e.message

    if "lives" not in realtime_weather_data or len(realtime_weather_data["lives"]) == 0:
        # TODO: I am not sure how to judge if I get the realtime data. Waiting for such a case.
        return "There is no realtime weather data for this city"

    return realtime_weather_data["lives"][0]

if __name__ == "__main__":
    # Initialize and run the server
    mcp.run(transport='streamable-http')
