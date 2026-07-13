import asyncio
import logging
import urllib.parse
import requests

logger = logging.getLogger(__name__)

# Two independent neutral hosts
PROBE_URLS = [
    "https://api.ipify.org?format=json",
    "https://ifconfig.me/ip"
]

# Playwright/Chromium network errors representing connection issues
PROXY_NET_ERRORS = (
    "ERR_PROXY_CONNECTION_FAILED",
    "ERR_TUNNEL_CONNECTION_FAILED",
    "ERR_TIMED_OUT",
    "ERR_CONNECTION_CLOSED",
    "ERR_CONNECTION_RESET",
    "ERR_CONNECTION_ABORTED",
    "ERR_NAME_NOT_RESOLVED"
)


def is_proxy_level_error(exc: Exception) -> bool:
    """
    Classify if an exception is a Playwright/Chromium proxy network-level error.
    
    :param exc: The exception to inspect.
    :return: True if any proxy network error code is found in the exception message.
    """
    exc_str = str(exc)
    return any(err in exc_str for err in PROXY_NET_ERRORS)


def _check_once(proxy: dict, timeout: int) -> tuple[bool, str]:
    """
    Perform a single synchronous check against the PROBE_URLS using the proxy.
    
    Distinguishes connection-level failures (ConnectionError, ConnectTimeout) 
    from read timeouts/lags (ReadTimeout).
    
    :param proxy: Dict with keys: server, username, password.
    :param timeout: Connection timeout in seconds.
    :return: A tuple (alive, reason/status).
    """
    server = proxy.get("server", "").strip()
    username = proxy.get("username", "")
    password = proxy.get("password", "")

    # Clean scheme if present
    clean_server = server.replace("http://", "").replace("https://", "")

    # Format the proxy url with credentials quoted
    if username and password:
        quoted_user = urllib.parse.quote(username)
        quoted_pass = urllib.parse.quote(password)
        proxy_url = f"http://{quoted_user}:{quoted_pass}@{clean_server}"
    else:
        proxy_url = f"http://{clean_server}"

    proxies = {
        "http": proxy_url,
        "https": proxy_url
    }

    had_conn_error = False
    had_timeout = False

    for url in PROBE_URLS:
        try:
            response = requests.get(url, proxies=proxies, timeout=timeout)
            # ANY HTTP response (even 5xx) means the proxy successfully routed the request
            return True, f"alive {response.status_code}"
        except (requests.exceptions.ConnectTimeout, requests.exceptions.ProxyError, requests.exceptions.ConnectionError) as e:
            # Connection-level failure to or through the proxy
            had_conn_error = True
        except (requests.exceptions.ReadTimeout, requests.exceptions.RequestException) as e:
            # Read timeouts or other non-connection errors (considered a lag/timeout)
            had_timeout = True

    # After attempting all probes:
    if had_conn_error:
        # At least one connection-level error occurred and there were no successful responses
        return False, "proxy_down"
    elif had_timeout:
        # Only read timeouts occurred (no connection failures)
        return False, "lag"
    else:
        return False, "unknown"


async def confirm_proxy_dead(proxy: dict, retries: int = 3) -> bool:
    """
    Asynchronously verify if a proxy is dead by retrying with escalating timeouts.
    
    Only flags the proxy as DEAD (True) if all retry attempts consistently yield 'proxy_down'.
    If any attempt is alive or merely lagging/timing out, returns False.
    
    :param proxy: Dict containing proxy configuration.
    :param retries: Number of retry attempts.
    :return: True if confirmed dead, False if alive or lagging.
    """
    server = proxy.get("server", "")
    clean_server = server.replace("http://", "").replace("https://", "")
    if "@" in clean_server:
        clean_server = clean_server.split("@")[-1]

    for attempt in range(1, retries + 1):
        # Escalating timeouts: 8s, 16s, 24s...
        timeout = 8 * attempt
        logger.info(f"Checking proxy status for {clean_server} (attempt {attempt}/{retries}, timeout={timeout}s)...")
        
        alive, info = await asyncio.to_thread(_check_once, proxy, timeout)
        
        if alive:
            logger.info(f"Proxy {clean_server} is alive: {info}")
            return False
        
        if info == "lag":
            logger.info(f"Proxy {clean_server} is lagging/timing out, but connection established. Treating as alive.")
            return False
            
        logger.warning(f"Proxy {clean_server} connection check failed (attempt {attempt}/{retries}): {info}")
        
        if attempt < retries:
            await asyncio.sleep(2)

    logger.error(f"Proxy {clean_server} confirmed DEAD after {retries} connection failures.")
    return True
