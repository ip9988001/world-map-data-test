# Dover, DE 四源取样报告（自动生成）

> 生成时间：2026-10-17 09:55:23Z ｜ 运行位置：**GitHub Actions**（本机服务器零下载）
> 锚定参数：州 `DE`/FIPS `10`｜县 `Kent County`/FIPS `10001`｜市 `Dover`/Place FIPS `1021200`｜邮编 `19901`, `19904`｜BBox `[-75.6, 39.1, -75.45, 39.22]`

## 0. 四源状态

| 源 | 状态 | 关键数字 | 备注 |
|---|---|---|---|
| `overture` | ok | features_bbox=28027 / features_19901=24046 / main_state_hits=510 |  |
| `nad_arcgis` | ok | rows=28028 / rows_zip_main=12093 / main_state_hits=512 / fields_n=60 / channel=A-official-rest |  |
| `openaddresses` | ok | rows=92455 / main_state_hits=414 / targets=2 |  |
| `census_tiger` | ok | REST=zcta:2,place_dover:1,county_kent:1,state_de:0 |  |

## 1. NAD 正牌图层字段清单（交通部官方 xOi1kZaI0eWDREZv）

- 通道：`A-official-rest`　端点：`https://services.arcgis.com/xOi1kZaI0eWDREZv/ArcGIS/rest/services/Address_Points_from_National_Address_Database_view/FeatureServer/0`
- 动态解析到的字段总数：**60**
- 关键字段验收：`Add_Number`→`Add_Number`、`StreetName`→`StNam_Full`、`County`→`County`、`Plus_4`→`Plus_4`、`Addr_Type`→`Addr_Type`　✅ 全部就位

```
OBJECTID, AddNum_Pre, Add_Number, AddNum_Suf, AddNo_Full, St_PreMod, St_PreDir, St_PreTyp, St_PreSep, St_Name, St_PosTyp, St_PosDir, St_PosMod, StNam_Full, Building, Floor, Unit, Room, Seat, Addtl_Loc, SubAddress, LandmkName, County, Inc_Muni, Post_City, Census_Plc, Uninc_Comm, Nbrhd_Comm, NatAmArea, NatAmSub, Urbnztn_PR, PlaceOther, PlaceNmTyp, State, Zip_Code, Plus_4, UUID, AddAuth, AddrRefSys, Longitude, Latitude, NatGrid, Elevation, Placement, AddrPoint, Related_ID, RelateType, ParcelSrc, Parcel_ID, AddrClass, Lifecycle, Effective, Expire, DateUpdate, AnomStatus, LocatnDesc, Addr_Type, DeliverTyp, NAD_Source, DataSet_ID
```

### Zip_Code='19901' 首 3 条完整记录（键值对）

**#1**

```json
{
 "OBJECTID": 98102268,
 "AddNum_Pre": null,
 "Add_Number": 5921,
 "AddNum_Suf": null,
 "AddNo_Full": "5921",
 "St_PreMod": null,
 "St_PreDir": "West",
 "St_PreTyp": null,
 "St_PreSep": null,
 "St_Name": "DENNEYS",
 "St_PosTyp": "Road",
 "St_PosDir": null,
 "St_PosMod": null,
 "StNam_Full": "West DENNEYS Road",
 "Building": null,
 "Floor": null,
 "Unit": "APT I",
 "Room": null,
 "Seat": null,
 "Addtl_Loc": null,
 "SubAddress": "APT I",
 "LandmkName": null,
 "County": "Kent",
 "Inc_Muni": "Dover",
 "Post_City": "Dover",
 "Census_Plc": null,
 "Uninc_Comm": null,
 "Nbrhd_Comm": "Dover",
 "NatAmArea": null,
 "NatAmSub": null,
 "Urbnztn_PR": null,
 "PlaceOther": null,
 "PlaceNmTyp": null,
 "State": "DE",
 "Zip_Code": "19901",
 "Plus_4": null,
 "UUID": "13c299f4-553f-4c55-b13c-a2d80b9b518a",
 "AddAuth": "Kent County Delaware",
 "AddrRefSys": null,
 "Longitude": -75.55852402540219,
 "Latitude": 39.20332040984156,
 "NatGrid": "18SVJ5177439488",
 "Elevation": null,
 "Placement": "Unknown",
 "AddrPoint": "-75.55852402540219 39.20332040984156",
 "Related_ID": null,
 "RelateType": null,
 "ParcelSrc": null,
 "Parcel_ID": null,
 "AddrClass": "Numbered Thoroughfare Address",
 "Lifecycle": null,
 "Effective": null,
 "Expire": null,
 "DateUpdate": 1613735141000,
 "AnomStatus": null,
 "LocatnDesc": null,
 "Addr_Type": "Unknown",
 "DeliverTyp": null,
 "NAD_Source": "Kent County Delaware",
 "DataSet_ID": "{13c299f4-553f-4c55-b13c-a2d80b9b518a}"
}
```

**#2**

```json
{
 "OBJECTID": 98102269,
 "AddNum_Pre": null,
 "Add_Number": 5921,
 "AddNum_Suf": null,
 "AddNo_Full": "5921",
 "St_PreMod": null,
 "St_PreDir": "West",
 "St_PreTyp": null,
 "St_PreSep": null,
 "St_Name": "DENNEYS",
 "St_PosTyp": "Road",
 "St_PosDir": null,
 "St_PosMod": null,
 "StNam_Full": "West DENNEYS Road",
 "Building": null,
 "Floor": null,
 "Unit": "APT D",
 "Room": null,
 "Seat": null,
 "Addtl_Loc": null,
 "SubAddress": "APT D",
 "LandmkName": null,
 "County": "Kent",
 "Inc_Muni": "Dover",
 "Post_City": "Dover",
 "Census_Plc": null,
 "Uninc_Comm": null,
 "Nbrhd_Comm": "Dover",
 "NatAmArea": null,
 "NatAmSub": null,
 "Urbnztn_PR": null,
 "PlaceOther": null,
 "PlaceNmTyp": null,
 "State": "DE",
 "Zip_Code": "19901",
 "Plus_4": null,
 "UUID": "31b2851a-88da-42cf-aab1-f1e13f267e33",
 "AddAuth": "Kent County Delaware",
 "AddrRefSys": null,
 "Longitude": -75.55852402540219,
 "Latitude": 39.20332040984156,
 "NatGrid": "18SVJ5177439488",
 "Elevation": null,
 "Placement": "Unknown",
 "AddrPoint": "-75.55852402540219 39.20332040984156",
 "Related_ID": null,
 "RelateType": null,
 "ParcelSrc": null,
 "Parcel_ID": null,
 "AddrClass": "Numbered Thoroughfare Address",
 "Lifecycle": null,
 "Effective": null,
 "Expire": null,
 "DateUpdate": 1613735141000,
 "AnomStatus": null,
 "LocatnDesc": null,
 "Addr_Type": "Unknown",
 "DeliverTyp": null,
 "NAD_Source": "Kent County Delaware",
 "DataSet_ID": "{31b2851a-88da-42cf-aab1-f1e13f267e33}"
}
```

**#3**

```json
{
 "OBJECTID": 98102270,
 "AddNum_Pre": null,
 "Add_Number": 5921,
 "AddNum_Suf": null,
 "AddNo_Full": "5921",
 "St_PreMod": null,
 "St_PreDir": "West",
 "St_PreTyp": null,
 "St_PreSep": null,
 "St_Name": "DENNEYS",
 "St_PosTyp": "Road",
 "St_PosDir": null,
 "St_PosMod": null,
 "StNam_Full": "West DENNEYS Road",
 "Building": null,
 "Floor": null,
 "Unit": "APT C",
 "Room": null,
 "Seat": null,
 "Addtl_Loc": null,
 "SubAddress": "APT C",
 "LandmkName": null,
 "County": "Kent",
 "Inc_Muni": "Dover",
 "Post_City": "Dover",
 "Census_Plc": null,
 "Uninc_Comm": null,
 "Nbrhd_Comm": "Dover",
 "NatAmArea": null,
 "NatAmSub": null,
 "Urbnztn_PR": null,
 "PlaceOther": null,
 "PlaceNmTyp": null,
 "State": "DE",
 "Zip_Code": "19901",
 "Plus_4": null,
 "UUID": "41ae0bbf-4544-4caf-9994-8c15726beead",
 "AddAuth": "Kent County Delaware",
 "AddrRefSys": null,
 "Longitude": -75.55852402540219,
 "Latitude": 39.20332040984156,
 "NatGrid": "18SVJ5177439488",
 "Elevation": null,
 "Placement": "Unknown",
 "AddrPoint": "-75.55852402540219 39.20332040984156",
 "Related_ID": null,
 "RelateType": null,
 "ParcelSrc": null,
 "Parcel_ID": null,
 "AddrClass": "Numbered Thoroughfare Address",
 "Lifecycle": null,
 "Effective": null,
 "Expire": null,
 "DateUpdate": 1613735141000,
 "AnomStatus": null,
 "LocatnDesc": null,
 "Addr_Type": "Unknown",
 "DeliverTyp": null,
 "NAD_Source": "Kent County Delaware",
 "DataSet_ID": "{41ae0bbf-4544-4caf-9994-8c15726beead}"
}
```

### 通道 C：Release 24 官方样本附件

- `data/dover/raw/NAD_r24_SAMPLE_First_and_Last_20_lines.txt` — 17863 B｜表头 1 列
- `data/dover/raw/TXT Technical Parsing Note.txt` — 731 B

## 2. 三源并排对齐样本（邮编 19901/19904 + 街道含 MAIN 或 STATE）

合计 **1414** 行 → `data/dover/align_19901_main_state.csv`
各源命中：{"overture": 500, "nad_arcgis": 500, "openaddresses": 414}

## 3. 产物清单

- `data/dover/align_19901_main_state.csv` — 105,019 B
- `data/dover/align_src_nad_arcgis.csv` — 33,118 B
- `data/dover/align_src_openaddresses.csv` — 21,390 B
- `data/dover/align_src_overture.csv` — 34,794 B
- `data/dover/manifest.json` — 11,463 B
- `data/dover/nad_dover_19901.csv` — 33,717 B
- `data/dover/nad_dover_full.csv` — 225,829 B
- `data/dover/openaddresses_19901.csv` — 27,236 B
- `data/dover/overture_19901.csv` — 33,707 B
- `data/dover/raw/NAD_r24_SAMPLE_First_and_Last_20_lines.txt` — 17,863 B
- `data/dover/raw/TXT Technical Parsing Note.txt` — 731 B
- `data/dover/raw/nad_dover_19901.geojson.gz` — 783,143 B
- `data/dover/raw/nad_dover_official.geojson.gz` — 2,081,649 B
- `data/dover/raw/nad_official_metadata.json` — 1,206,272 B
- `data/dover/raw/openaddresses_city_of_dover.zip` — 310,206 B
- `data/dover/raw/openaddresses_kent.zip` — 1,908,081 B
- `data/dover/raw/overture_dover.geojson.gz` — 2,085,794 B
- `data/dover/raw/overture_dover.geojson.state` — 358 B
- `data/dover/raw/tiger_county_kent.json` — 99,118 B
- `data/dover/raw/tiger_place_dover.json` — 114,238 B
- `data/dover/raw/tiger_state_de.json` — 78 B
- `data/dover/raw/tiger_zcta.json` — 173,558 B
- `data/dover/raw/tl_2024_10001_addrfeat.zip` — 1,409,495 B
- `data/dover/raw/tl_2024_10_place.zip` — 444,861 B
- `data/dover/task001/fillrate_4sources.csv` — 6,178 B
- `data/dover/task001/relay_post.md` — 10,752 B
- `data/dover/task001/task001_records.csv` — 37,089 B
- `data/dover/task001/task001_records.jsonl` — 61,336 B
- `data/dover/task001/tiger_boundary_de_10.json` — 222,086 B
- `data/dover/task001/tiger_boundary_dover_10' AND BASENAME.json` — 115,976 B
- `data/dover/task001/tiger_boundary_kent_10' AND COUNTY.json` — 100,774 B
- `data/dover/task001/tiger_boundary_zcta5_19901.json` — 90,133 B
- `data/dover/task001/tiger_boundary_zcta5_19904.json` — 87,748 B
- `data/dover/task003/dover_funnel.json` — 3,025 B
- `data/dover/task003/dover_golden_addresses.csv` — 11,822,295 B
- `data/dover/task003/dover_golden_addresses.jsonl` — 33,170,436 B
- `data/dover/task003/dover_task003_summary.json` — 8,472 B
- `data/dover/task003/five_address_4source_comparisons.json` — 23,804 B
- `data/dover/task003/golden_fillrate_24fields.csv` — 815 B
- `data/dover/task003/golden_sample_50.csv` — 22,319 B

## 4. 口径与已知边界

- NAD 只走交通部官方正牌三通道（REST → WFS → Socrata 样本）；**第三方阉割镜像 `Do88DoK2xjTUCXd1 / USA_NAD_Addresses` 已在代码层拉黑**（它只有 9 个 OSM 简化字段、2023 停更，缺 Plus_4 / County / Post_Comm / LandmkName 与街道 8 级拆分）。
- 官方视图偶发抽风，脚本带 2s/5s/10s 指数退避重试。
- `outFields` 由元数据动态生成（非手写、非 `*`），保证 100% 取到原版字段。
- OpenAddresses 的 run id 每次会变，机器人每次现查首页取最新 zip。
- 三源字段命名各异，本报告只做**并排对齐**，不做合并 —— 合成规则待架构师定稿。

