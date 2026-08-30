def parse_user_agent(ua_string: str) -> tuple[str, str]:
    if not ua_string:
        return ('Dispositivo desconocido', 'Navegador desconocido')
    
    ua = ua_string.lower()
    
    os = 'Dispositivo'
    if 'windows' in ua:
        os = 'Windows PC'
    elif 'macintosh' in ua or 'mac os' in ua:
        os = 'macOS Apple'
    elif 'android' in ua:
        os = 'Android Móvil'
    elif 'iphone' in ua:
        os = 'iPhone Apple'
    elif 'ipad' in ua:
        os = 'iPad Tablet'
    elif 'linux' in ua:
        os = 'Linux'

    browser = 'Navegador Web'
    if 'edg/' in ua:
        browser = 'Microsoft Edge'
    elif 'chrome/' in ua and 'safari' in ua and 'edg' not in ua:
        browser = 'Google Chrome'
    elif 'firefox/' in ua:
        browser = 'Mozilla Firefox'
    elif 'safari/' in ua and 'chrome' not in ua:
        browser = 'Apple Safari'
    elif 'opera' in ua or 'opr/' in ua:
        browser = 'Opera'

    return (os, browser)
