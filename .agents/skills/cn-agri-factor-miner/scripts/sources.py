"""Commodity routing and transparent research-source plans; no invented access."""
import datetime as dt

# Symbols are discovery hints; execution still requires effective-dated verification.
PROFILES = {
 'soybean_meal': ('豆粕', 'M', 'DCE', 'oilseeds', '大豆 到港 压榨 豆粕 库存 饲料需求', ['meal_stock', 'weekly_meal_use', 'raw_stock', 'arrivals_14d', 'planned_crush_14d']),
 'soybean_oil': ('豆油', 'Y', 'DCE', 'oilseeds', '大豆 压榨 豆油 库存 食用油 消费', ['oil_stock', 'weekly_oil_use', 'raw_stock', 'planned_crush_14d']),
 'soybean': ('大豆', 'A', 'DCE', 'oilseeds', '大豆 产量 播种 进口 库存', ['crop_production', 'imports', 'physical_stock']),
 'palm_oil': ('棕榈油', 'P', 'DCE', 'oilseeds', '棕榈油 MPOB 产量 出口 中国 港口 库存', ['physical_stock', 'imports', 'production', 'exports']),
 'rapeseed_meal': ('菜粕', 'RM', 'CZCE', 'oilseeds', '油菜籽 进口 压榨 菜粕 库存 水产饲料', ['physical_stock', 'imports', 'crush', 'feed_demand']),
 'rapeseed_oil': ('菜油', 'OI', 'CZCE', 'oilseeds', '菜油 油菜籽 进口 库存 消费', ['physical_stock', 'imports', 'crush', 'consumption']),
 'corn': ('玉米', 'C', 'DCE', 'grains', '玉米 产量 进口 深加工 库存 饲料', ['physical_stock', 'crop_production', 'imports', 'feed_demand']),
 'corn_starch': ('玉米淀粉', 'CS', 'DCE', 'grains', '玉米淀粉 开机率 库存 加工利润', ['physical_stock', 'production', 'operating_rate']),
 'wheat': ('强麦', 'WH', 'CZCE', 'grains', '小麦 产量 库存 最低收购价 饲用替代', ['physical_stock', 'crop_production', 'feed_demand']),
 'rice': ('粳米', 'RR', 'DCE', 'grains', '稻谷 粳米 产量 库存 消费', ['physical_stock', 'crop_production', 'consumption']),
 'hog': ('生猪', 'LH', 'DCE', 'livestock', '生猪 能繁母猪 存栏 出栏 屠宰 均重', ['breeding_sows', 'slaughter', 'carcass_weight']),
 'egg': ('鸡蛋', 'JD', 'DCE', 'eggs', '鸡蛋 在产蛋鸡 补栏 淘汰 库存', ['laying_hens', 'placements', 'culling', 'physical_stock']),
 'apple': ('苹果', 'AP', 'CZCE', 'fruit', '苹果 冷库 库存 出库 产量 优果率', ['physical_stock', 'shipments', 'crop_production']),
 'jujube': ('红枣', 'CJ', 'CZCE', 'fruit', '红枣 产量 库存 等级 消费', ['physical_stock', 'crop_production', 'consumption']),
 'sugar': ('白糖', 'SR', 'CZCE', 'sugar', '食糖 产糖 销糖 进口 库存 巴西 印度', ['physical_stock', 'production', 'sales', 'imports']),
 'cotton': ('棉花', 'CF', 'CZCE', 'cotton', '棉花 商业库存 工业库存 纺纱 开机 进口', ['physical_stock', 'imports', 'mill_use', 'operating_rate']),
 'peanut': ('花生', 'PK', 'CZCE', 'oilseeds', '花生 产量 到货 压榨 库存', ['physical_stock', 'crop_production', 'crush']),
}
ALIASES = {'小麦': 'wheat', '稻米': 'rice', '菜籽粕': 'rapeseed_meal', '菜籽油': 'rapeseed_oil', '糖': 'sugar'}


def commodity(value):
    if value in PROFILES: return value
    if value in ALIASES: return ALIASES[value]
    for key, p in PROFILES.items():
        if value in (p[0], p[1]): return key
    raise ValueError('OUT_OF_SCOPE_OR_AMBIGUOUS: identify a Chinese agricultural futures product: ' + value)


def make_plan(values, start, end):
    first, last = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    if first > last: raise ValueError('start must be <= end')
    members = list(dict.fromkeys(commodity(v) for v in values))
    if not members: raise ValueError('At least one commodity required')
    tasks, queries, needs = [], [], []
    for key in members:
        name, symbol, exchange, family, words, fields = PROFILES[key]
        tasks.append({'id': key + '-warehouse', 'provider': 'tushare', 'api': 'fut_wsr',
                      'params': {'symbol': symbol, 'exchange': exchange, 'start_date': first.strftime('%Y%m%d'), 'end_date': last.strftime('%Y%m%d')},
                      'fields': 'trade_date,symbol,fut_name,warehouse,wh_id,vol,unit,exchange,area,year,grade,brand,place,is_ct',
                      'commodity': key, 'role': 'registered_receipts_not_total_inventory'})
        tasks.append({'id': key + '-contracts', 'provider': 'tushare', 'api': 'fut_basic',
                      'params': {'exchange': exchange, 'fut_code': symbol}, 'fields': '',
                      'commodity': key, 'role': 'metadata_requires_primary_exchange_verification'})
        for source, q in [('official_cn', 'site:moa.gov.cn ' + words), ('trade', 'site:customs.gov.cn ' + name + ' 进口 出口'),
                          ('exchange', 'site:' + ('dce.com.cn' if exchange == 'DCE' else 'czce.com.cn') + ' ' + name + ' 仓单 交割 规则'),
                          ('industry', words + ' 周报 数据 统计口径')]:
            queries.append({'id': key + '-' + source, 'commodity': key, 'query': q + ' ' + end[:4], 'status': 'PENDING_HOST_SEARCH'})
        if family in ('oilseeds', 'grains', 'cotton', 'sugar'):
            queries.append({'id': key + '-global', 'commodity': key, 'query': 'site:usda.gov WASDE ' + {'oilseeds':'soybeans oilseeds','grains':'grains','cotton':'cotton','sugar':'sugar'}[family] + ' ' + end[:4], 'status': 'PENDING_HOST_SEARCH'})
        needs += [{'commodity': key, 'field': f, 'status': 'TO_DISCOVER'} for f in fields]
    return {'schema_version': 1, 'commodities': members, 'start': start, 'end': end, 'tasks': tasks,
            'searches': queries, 'fundamental_needs': needs,
            'market_needs': [{'commodity': k, 'capability': 'daily', 'status': 'VERIFY_CONTRACT_THEN_ROUTE',
                              'instruction': 'Use source_router.py daily: user-configured API/MCP, existing providers, then host discovery of usable daily APIs.'} for k in members],
            'choice': {'status': 'DISCOVER_INDICATOR_MAPPING', 'instruction': 'Use installed Choice docs/official indicator catalog; map csd/ctr/edb code, unit and sample before adding a query. Never invent EDB IDs.'},
            'limits': {'pages_per_request': 10, 'http_timeout_seconds': 25, 'max_download_bytes': 20000000},
            'note': 'Run host searches and API acquisition before claiming a data gap. Discovery symbols are not verified contract specifications.'}
