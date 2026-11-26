#!/usr/bin/env python3
"""Merge GeoNames + Census Gazetteer (ZCTA/places/counties) + ZCTA-county rel
into one US ZIP reference table, with cross-source confirmation flags.

Sources (all downloaded 2026-11-22):
  G: GeoNames US.txt (41,490 ZIPs) - zip -> place, state, county, lat/lon
  Z: Census Gazetteer 2024 ZCTA - ZCTA -> centroid lat/lon, area
  P: Census Gazetteer 2024 places - place name + state -> centroid
  R: Census ZCTA-county rel 2010 - ZCTA -> county GEOID + pop/housing/area %
  C: Census Gazetteer 2024 counties - state + county NAME -> GEOID (FIPS)

Output: us_zip_reference_merged_20261122.csv
"""
import csv, math, re, os

SRC = '/home/hatch/workspace/research_notes/reference-tables/sources'
OUT = '/home/hatch/workspace/research_notes/reference-tables/us_zip_reference_merged_v2_20261122.csv'
BY_STATE_DIR = '/home/hatch/workspace/research_notes/reference-tables/by-state'

STATE_NAMES = {
 'AL':'Alabama','AK':'Alaska','AZ':'Arizona','AR':'Arkansas','CA':'California',
 'CO':'Colorado','CT':'Connecticut','DE':'Delaware','DC':'District of Columbia',
 'FL':'Florida','GA':'Georgia','HI':'Hawaii','ID':'Idaho','IL':'Illinois',
 'IN':'Indiana','IA':'Iowa','KS':'Kansas','KY':'Kentucky','LA':'Louisiana',
 'ME':'Maine','MD':'Maryland','MA':'Massachusetts','MI':'Michigan','MN':'Minnesota',
 'MS':'Mississippi','MO':'Missouri','MT':'Montana','NE':'Nebraska','NV':'Nevada',
 'NH':'New Hampshire','NJ':'New Jersey','NM':'New Mexico','NY':'New York',
 'NC':'North Carolina','ND':'North Dakota','OH':'Ohio','OK':'Oklahoma','OR':'Oregon',
 'PA':'Pennsylvania','RI':'Rhode Island','SC':'South Carolina','SD':'South Dakota',
 'TN':'Tennessee','TX':'Texas','UT':'Utah','VT':'Vermont','VA':'Virginia',
 'WA':'Washington','WV':'West Virginia','WI':'Wisconsin','WY':'Wyoming',
 'PR':'Puerto Rico','GU':'Guam','VI':'Virgin Islands','MP':'Northern Mariana Islands',
 'AS':'American Samoa',
}

def norm(s):
    s = (s or '').strip().lower()
    s = re.sub(r'[^a-z0-9 ]', '', s)
    return re.sub(r'\s+', ' ', s).strip()

def strip_place_suffix(name):
    """Strip Census LSAD suffix words iteratively: 'Agawam Town city' -> 'Agawam'."""
    s = name.strip()
    changed = True
    while changed:
        changed = False
        for suf in (' cdp', ' city', ' town', ' village', ' borough', ' township',
                    ' municipality', ' corporation', ' unified government'):
            if s.lower().endswith(suf):
                s = s[:-len(suf)].strip()
                changed = True
    return s

def norm_county(s):
    s = norm(s)
    if s.startswith('city of '):
        s = s[len('city of '):]
    for suf in (' county', ' parish', ' borough', ' municipio', ' census area', ' city'):
        if s.endswith(suf):
            s = s[:-len(suf)]
    return s.strip()

# GeoNames calls CT's post-2022 planning regions by short names; Census uses
# the full '... Planning Region' names. 'Connecticut Metropolitan' is the
# Greater Bridgeport region (MetroCOG).
CT_ALIAS = {
    'capitol region': 'capitol planning region',
    'south central regional': 'south central connecticut planning region',
    'naugatuck valley': 'naugatuck valley planning region',
    'southeastern connecticut': 'southeastern connecticut planning region',
    'northwest hills': 'northwest hills planning region',
    'northeastern connecticut': 'northeastern connecticut planning region',
    'lower connecticut river valley': 'lower connecticut river valley planning region',
    'western connecticut': 'western connecticut planning region',
    'connecticut metropolitan': 'greater bridgeport planning region',
}

def county_key(state, county_name):
    k = norm_county(county_name)
    if state == 'CT':
        k = CT_ALIAS.get(k, k)
    return k

# --- County polygons (Census cartographic boundary 2024) for point-in-polygon ---
POLY = None
try:
    import shapefile as _shp
    from shapely.geometry import shape as _shape
    from shapely.strtree import STRtree as _STRtree
    _sf = _shp.Reader(os.path.join(SRC, 'cb_2024_us_county_500k.shp'))
    _polys, _geoids = [], []
    for _rec in _sf.shapeRecords():
        _polys.append(_shape(_rec.shape.__geo_interface__))
        _geoids.append(_rec.record['GEOID'])
    _tree = _STRtree(_polys)
    POLY = (_polys, _geoids, _tree)
    print('county polygons loaded:', len(_polys))
except Exception as e:
    print('polygon load failed:', e)

def county_by_point(lat, lon):
    """County GEOID containing the point, or None."""
    if POLY is None or lat is None or lon is None:
        return None
    polys, geoids, tree = POLY
    from shapely.geometry import Point as _Point
    pt = _Point(lon, lat)
    for idx in tree.query(pt):
        if polys[idx].contains(pt):
            return geoids[idx]
    # fall back: nearest polygon within ~5 km (coastal/edge centroids)
    nearest = tree.nearest(pt)
    if nearest is not None and polys[nearest].distance(pt) < 0.05:
        return geoids[nearest]
    return None
    s = norm(s)
    for suf in (' county', ' parish', ' borough', ' municipio', ' census area', ' city'):
        if s.endswith(suf):
            s = s[:-len(suf)]
    return s.strip()

def haversine_km(lat1, lon1, lat2, lon2):
    r = math.radians
    dlat = r(lat2 - lat1); dlon = r(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(r(lat1))*math.cos(r(lat2))*math.sin(dlon/2)**2
    return 6371 * 2 * math.asin(math.sqrt(a))

# --- C: county reference (state, county-name-normalized) -> FIPS ---
county_fips = {}   # (state, norm_county) -> GEOID
county_name_by_fips = {}
with open(os.path.join(SRC, '2024_Gaz_counties_national.txt'), encoding='utf-8') as f:
    rdr = csv.DictReader(f, delimiter='\t')
    rdr.fieldnames = [fn.strip() for fn in rdr.fieldnames]
    for row in rdr:
        st, geoid, name = row['USPS'], row['GEOID'], row['NAME']
        county_fips[(st, norm_county(name))] = geoid
        county_name_by_fips[geoid] = name
print('county ref entries:', len(county_fips))

# --- G: GeoNames ---
geo = {}  # zip -> dict
with open(os.path.join(SRC, 'geonames-US.txt'), encoding='utf-8') as f:
    for row in csv.reader(f, delimiter='\t'):
        if len(row) < 10:
            continue
        geo[row[1]] = {'place': row[2], 'state': row[4], 'county': row[5],
                       'lat': float(row[8]) if row[8] else None,
                       'lon': float(row[9]) if row[9] else None}
print('geonames zips:', len(geo))

# --- Z: Gazetteer ZCTA ---
zcta = {}
with open(os.path.join(SRC, '2024_Gaz_zcta_national.txt'), encoding='utf-8') as f:
    rdr = csv.DictReader(f, delimiter='\t')
    rdr.fieldnames = [fn.strip() for fn in rdr.fieldnames]
    for row in rdr:
        zcta[row['GEOID']] = {'lat': float(row['INTPTLAT']), 'lon': float(row['INTPTLONG']),
                              'area_sqmi': float(row['ALAND_SQMI'])}
print('gazetteer zctas:', len(zcta))

# --- R: ZCTA-county rel 2010: primary county by population share ---
rel_primary = {}  # zcta -> (geoid, zpop_pct)
with open(os.path.join(SRC, 'zcta_county_rel_10.txt'), encoding='utf-8') as f:
    for row in csv.DictReader(f):
        z = row['ZCTA5']
        try:
            pop_pct = float(row['ZPOPPCT'] or 0)
            area_pct = float(row['ZAREAPCT'] or 0)
        except ValueError:
            continue
        score = pop_pct if pop_pct > 0 else area_pct
        cur = rel_primary.get(z)
        if cur is None or score > cur[1]:
            rel_primary[z] = (row['GEOID'], score)
print('rel zctas:', len(rel_primary))

# --- H: HUD USPS ZIP-COUNTY Q2 2026 (ZIP-COUNTY_062026.xlsx) ---
# One row per ZIP x county. Primary county = max res_ratio (residential share);
# if all res_ratio are 0, max tot_ratio. City = USPS preferred city (upper case).
def hud_title(s):
    t = (s or '').strip().title()
    for w in ('Afb', 'Apo', 'Fpo'):
        t = t.replace(' ' + w, ' ' + w.upper())
    return t

hud = {}  # zip -> {'geoid': str, 'share': float, 'city': str, 'state': str, 'nrows': int}
import openpyxl as _oxl
_wb = _oxl.load_workbook(os.path.join(SRC, 'ZIP-COUNTY_062026.xlsx'), read_only=True, data_only=True)
_ws = _wb.active
_hrows = list(_ws.iter_rows(values_only=True))
for _r in _hrows[1:]:
    _zip, _geoid, _city, _state, _res, _bus, _oth, _tot = _r
    _zip = str(_zip).zfill(5)
    _res = float(_res or 0); _tot = float(_tot or 0)
    _score = _res if _res > 0 else _tot
    _cur = hud.get(_zip)
    if _cur is None:
        hud[_zip] = {'geoid': str(_geoid), 'share': _score * 100,
                     'city': hud_title(_city), 'state': _state, 'nrows': 1}
    else:
        _cur['nrows'] += 1
        if _score * 100 > _cur['share']:
            _cur.update({'geoid': str(_geoid), 'share': _score * 100,
                         'city': hud_title(_city), 'state': _state})
print('hud zips:', len(hud))

# --- P: Gazetteer places: (state, norm name) -> (lat, lon); plus per-state list ---
places = {}  # (state, norm name) -> (lat, lon)
places_by_state = {}
with open(os.path.join(SRC, '2024_Gaz_place_national.txt'), encoding='utf-8') as f:
    rdr = csv.DictReader(f, delimiter='\t')
    rdr.fieldnames = [fn.strip() for fn in rdr.fieldnames]
    for row in rdr:
        st, name = row['USPS'], row['NAME']
        # index under both full name and suffix-stripped base name
        for variant in {norm(name), norm(strip_place_suffix(name))}:
            key = (st, variant)
            if key not in places:
                places[key] = (float(row['INTPTLAT']), float(row['INTPTLONG']))
        places_by_state.setdefault(st, []).append((norm(strip_place_suffix(name)), float(row['INTPTLAT']), float(row['INTPTLONG'])))
print('gazetteer places:', len(places))

# --- Merge ---
rows = []
stats = {'total': 0, 'city_confirmed': 0, 'city_unconfirmed': 0, 'city_from_nearest': 0,
         'city_missing': 0, 'county_confirmed': 0, 'county_conflict': 0,
         'county_fips_missing': 0, 'in_zcta': 0, 'geonames_only': 0, 'zcta_only': 0}
allzips = sorted(set(geo) | set(zcta) | set(hud))
for z in allzips:
    g = geo.get(z)
    zc = zcta.get(z)
    h = hud.get(z)
    flags, sources = [], []
    if g:
        sources.append('G')
    if zc:
        sources.append('Z'); stats['in_zcta'] += 1
    if h:
        sources.append('H')
    # state: HUD (USPS) wins; flag a disagreement with GeoNames
    state = g['state'] if g else None
    if h and state and h['state'] != state:
        flags.append('state_conflict:hud=%s geonames=%s' % (h['state'], state))
        state = h['state']
    elif h and not state:
        state = h['state']
    # county authority: HUD primary (2026 Q2, residential share) else rel 2010
    #  H = HUD primary (share in %), C = polygon containing ZCTA centroid,
    #  G = GeoNames county name -> FIPS
    if h:
        rel = (h['geoid'], h['share'])
        auth_src = 'hud'
    else:
        rel = rel_primary.get(z)
        auth_src = 'rel'
    if rel and auth_src == 'rel':
        sources.append('R')
    fips_geo = None
    if g and state:
        fips_geo = county_fips.get((state, county_key(state, g['county'])))
    fips_poly = county_by_point(zc['lat'], zc['lon']) if zc else None
    if fips_poly:
        sources.append('C')
    county = g['county'] if g else None
    fips = None
    county_ok = None
    if rel and rel[0] not in county_name_by_fips:
        # stale rel GEOID (e.g. CT legacy counties replaced by planning regions
        # in 2022-2024): rel cannot be trusted here, polygon wins
        if fips_poly:
            fips = fips_poly
            county_ok = True; stats['county_confirmed'] += 1
            flags.append('county_auth_stale:%s=%s polygon=%s(%s)' % (
                auth_src, rel[0], county_name_by_fips.get(fips_poly, '?'), fips_poly))
        elif fips_geo:
            fips = fips_geo
            county_ok = True; stats['county_confirmed'] += 1
            flags.append('county_auth_stale_geonames')
    elif rel and fips_poly and rel[0] != fips_poly:
        # rel is population-based; polygon is centroid-based. A large rural
        # ZCTA's centroid often sits in a neighbour county while its people
        # live in the rel county - that is a centroid artefact, not an error.
        fips = rel[0]
        if rel[1] >= 85:
            county_ok = True; stats['county_confirmed'] += 1
            flags.append('county_centroid_neighbor:%s=%s(%s,%.0f%%) polygon=%s(%s)' % (
                auth_src,
                county_name_by_fips.get(rel[0], '?'), rel[0], rel[1],
                county_name_by_fips.get(fips_poly, '?'), fips_poly))
        elif rel[1] < 60:
            county_ok = True; stats['county_confirmed'] += 1
            flags.append('county_multi:%s_primary=%s(%s,%.0f%%) polygon=%s(%s)' % (
                auth_src,
                county_name_by_fips.get(rel[0], '?'), rel[0], rel[1],
                county_name_by_fips.get(fips_poly, '?'), fips_poly))
        else:
            # 2026-11-22 裁定（Muse 决定）：人口占比 60–85% 仍以人口主县为准。
            # 理由：本表是给地址按邮编回填县，人口主县是唯一合理的单值答案；
            # 点面判断的中心点落在邻县是大面积农村邮编的常见假象（中心点在邻县、
            # 人住在主县），不是主县错的证据。证据全留在 flag 里，可审计。
            county_ok = True; stats['county_confirmed'] += 1
            flags.append('county_multi_resolved:%s=%s(%s,%.0f%%) polygon=%s(%s)' % (
                auth_src,
                county_name_by_fips.get(rel[0], '?'), rel[0], rel[1],
                county_name_by_fips.get(fips_poly, '?'), fips_poly))
    elif rel:
        fips = rel[0]
        if fips_poly == rel[0] or fips_geo == rel[0]:
            county_ok = True; stats['county_confirmed'] += 1
        elif rel[1] < 60:
            county_ok = True; stats['county_confirmed'] += 1
            flags.append('county_multi:%s_primary=%s(%s,%.0f%%)' % (
                auth_src,
                county_name_by_fips.get(rel[0], '?'), rel[0], rel[1]))
        else:
            county_ok = True; stats['county_confirmed'] += 1
            flags.append('county_single_source_auth')
    elif fips_poly:
        fips = fips_poly
        if fips_geo == fips_poly:
            county_ok = True; stats['county_confirmed'] += 1
        else:
            county_ok = True; stats['county_confirmed'] += 1
            flags.append('county_from_polygon')
    elif fips_geo:
        fips = fips_geo
        county_ok = True; stats['county_confirmed'] += 1
        flags.append('county_single_source_geonames')
    if fips:
        cname = county_name_by_fips.get(fips, '')
        if cname:
            county = re.sub(r'\s+(County|Parish|Borough|Municipio|city)$', '', cname).strip()
    if not fips:
        stats['county_fips_missing'] += 1
        flags.append('county_fips_missing')
    # city: HUD city is the USPS preferred city; GeoNames place is the fallback.
    # HUD city wins; a disagreement with GeoNames is flagged, not silently dropped.
    city = None
    city_ok = None
    if h:
        city = h['city']
        if g and g['place']:
            if norm(h['city']) == norm(g['place']):
                city_ok = True; stats['city_confirmed'] += 1
            else:
                city_ok = False; stats['city_unconfirmed'] += 1
                flags.append('city_diff_hud_geonames:hud=%s geonames=%s' % (h['city'], g['place']))
        elif state and (state, norm(city)) in places:
            city_ok = True; sources.append('P'); stats['city_confirmed'] += 1
        else:
            city_ok = False; stats['city_unconfirmed'] += 1
            flags.append('city_not_in_gazetteer_places')
    elif g and g['place']:
        city = g['place']
        if state:
            if (state, norm(city)) in places:
                city_ok = True; sources.append('P'); stats['city_confirmed'] += 1
            else:
                city_ok = False; stats['city_unconfirmed'] += 1
                flags.append('city_not_in_gazetteer_places')
    elif zc:
        # no geonames: nearest gazetteer place in any state within 15 km of centroid
        best = None
        for st, lst in places_by_state.items():
            for (nm, la, lo) in lst:
                d = haversine_km(zc['lat'], zc['lon'], la, lo)
                if best is None or d < best[0]:
                    best = (d, nm, st)
        if best and best[0] <= 15:
            city = best[1].title()
            state = best[2]
            city_ok = False; stats['city_from_nearest'] += 1
            flags.append('city_from_nearest_place:%.1fkm' % best[0])
            # re-derive county/fips from rel if still missing
            if not fips and rel:
                fips = rel[0]
                county = county_name_by_fips.get(rel[0], '').replace(' County', '').replace(' Parish', '')
        else:
            stats['city_missing'] += 1
            flags.append('city_missing')
    else:
        stats['city_missing'] += 1
        flags.append('city_missing')
    if g and not zc:
        stats['geonames_only'] += 1
    if zc and not g:
        stats['zcta_only'] += 1
    if not state:
        # last resort: infer state from ZIP prefix via county fips state code
        if fips:
            state = {v: k for k, v in {'AL':'01','AK':'02','AZ':'04','AR':'05','CA':'06','CO':'08','CT':'09','DE':'10','DC':'11','FL':'12','GA':'13','HI':'15','ID':'16','IL':'17','IN':'18','IA':'19','KS':'20','KY':'21','LA':'22','ME':'23','MD':'24','MA':'25','MI':'26','MN':'27','MS':'28','MO':'29','MT':'30','NE':'31','NV':'32','NH':'33','NJ':'34','NM':'35','NY':'36','NC':'37','ND':'38','OH':'39','OK':'40','OR':'41','PA':'42','RI':'44','SC':'45','SD':'46','TN':'47','TX':'48','UT':'49','VT':'50','VA':'51','WA':'53','WV':'54','WI':'55','WY':'56','PR':'72','GU':'66','VI':'78','MP':'69','AS':'60'}.items()}.get(fips[:2])
    rows.append({
        'zip': z,
        'city_primary': city or '',
        'city_confirmed': 'yes' if city_ok else ('no' if city_ok is False else ''),
        'state_abbr': state or '',
        'state_name': STATE_NAMES.get(state, '') if state else '',
        'county': county or '',
        'county_fips': fips or '',
        'county_confirmed': 'yes' if county_ok else ('no' if county_ok is False else ''),
        'in_zcta': 'yes' if zc else 'no',
        'sources': '+'.join(sources),
        'flags': '; '.join(flags),
    })
    stats['total'] += 1

FIELDS = ['zip','city_primary','city_confirmed','state_abbr',
        'state_name','county','county_fips','county_confirmed','in_zcta','sources','flags']
with open(OUT, 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=FIELDS)
    w.writeheader(); w.writerows(rows)

# per-state split: one file per state (rows with no state -> _unknown.csv)
os.makedirs(BY_STATE_DIR, exist_ok=True)
by_state = {}
for r in rows:
    by_state.setdefault(r['state_abbr'] or '_unknown', []).append(r)
for abbr, rs in sorted(by_state.items()):
    with open(os.path.join(BY_STATE_DIR, abbr + '.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader(); w.writerows(rs)
print('by-state files:', len(by_state), 'total rows in split:',
      sum(len(v) for v in by_state.values()))

print('--- merge stats ---')
for k, v in stats.items():
    print(k, v)
# sample conflicts
print('--- sample county conflicts (first 15) ---')
n = 0
for r in rows:
    if 'county_conflict' in r['flags']:
        print(r['zip'], r['city_primary'], r['state_abbr'], r['county'], r['county_fips'], '|', r['flags'])
        n += 1
        if n >= 15: break
print('--- sample city unconfirmed (first 10) ---')
n = 0
for r in rows:
    if 'city_not_in_gazetteer_places' in r['flags']:
        print(r['zip'], r['city_primary'], r['state_abbr'], r['county'])
        n += 1
        if n >= 10: break
print('--- sample city missing (first 10) ---')
n = 0
for r in rows:
    if 'city_missing' in r['flags']:
        print(r['zip'], r['state_abbr'], r['county'], r['county_fips'], r['sources'])
        n += 1
        if n >= 10: break
