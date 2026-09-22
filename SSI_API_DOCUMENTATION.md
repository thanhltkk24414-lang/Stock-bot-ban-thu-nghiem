# SSI iBoard API Documentation

## Overview

This document describes the API endpoints from `SSI_RAW_API.json` used by SSI iBoard / FiinGroup-backed services for Vietnamese stock market and company data.

**Base URLs:**
- iBoard Company Statistics: `https://iboard-api.ssi.com.vn/statistics/company/ssmi`
- Fiin Fundamental: `https://fiin-fundamental.ssi.com.vn`

**Tested With:** `curl -sS -L -A "Mozilla/5.0" -H "Accept: application/json"`

> **Test note:** All `iboard-api.ssi.com.vn` endpoints returned HTTP `200` JSON during curl testing on June 2, 2026. The `fiin-fundamental.ssi.com.vn` balance sheet endpoint returned HTTP `403` HTML (`Blocked - SSI` / Cloudflare challenge) when tested with curl, including with browser-like headers.

---

## 1. Common Response Format

Most iBoard endpoints return the same JSON envelope:

```json
{
  "code": "SUCCESS",
  "message": "Get ... data success",
  "data": [],
  "paging": {
    "total": 54,
    "page": 1,
    "pageSize": 10
  },
  "status": "ok"
}
```

**Common Fields:**
- `code` - API result code, usually `SUCCESS`
- `message` - Human-readable result message
- `data` - Endpoint-specific data object or array
- `paging` - Pagination metadata; can be `null`
- `status` - API status, usually `ok`

---

## 2. Company Module

### 2.1 Get Company Profile
**Endpoint:** `GET /company-profile`

**Full URL:** `https://iboard-api.ssi.com.vn/statistics/company/ssmi/company-profile?symbol={symbol}&language={language}`

**Description:** Retrieve company profile, listing information, business description, and contact details.

**Query Parameters:**
- `symbol` (required): Stock symbol, e.g. `ACB`
- `language` (optional): Language code, e.g. `vn` or `en`

**Response Format:** JSON Object (`data` is an object)
```json
{
  "code": "SUCCESS",
  "message": "Get company profile data success",
  "data": {
    "symbol": "ACB",
    "subSectorCode": "8355",
    "industryName": "Ngân hàng",
    "superSector": "Ngân hàng",
    "sector": "Ngân hàng",
    "subSector": "Ngân hàng",
    "foundingDate": "23/02/2006",
    "charterCapital": "51366565990000",
    "numberOfEmployee": 13022,
    "companyProfile": "<div>...</div>",
    "listingDate": "21/11/2006",
    "exchange": "HOSE",
    "firstPrice": "26400",
    "issueShare": "5136656599",
    "listedValue": "128930080634900.0",
    "companyName": "Ngân hàng Thương mại Cổ phần Á Châu",
    "quantity": 5136656599,
    "stockType": "Stock",
    "freeFloatRate": "0.85",
    "updateDate": "01/06/2026",
    "address": "442 Nguyễn Thị Minh Khai, Phường Bàn Cờ, Thành phố Hồ Chí Minh, Việt Nam",
    "website": "https://www.acb.com.vn",
    "telephone": "+84 28 39290999",
    "email": "acb@acb.com.vn",
    "isin": null,
    "fax": "+84 28 38399885"
  },
  "paging": null,
  "status": "ok"
}
```

**Field Mapping:**
- `symbol` → stock symbol
- `companyName` → company name
- `industryName`, `superSector`, `sector`, `subSector` → industry classification
- `foundingDate` → founding date (`DD/MM/YYYY`)
- `listingDate` → listing date (`DD/MM/YYYY`)
- `exchange` → listed exchange
- `firstPrice` → first/listing price
- `issueShare`, `quantity` → issued/listed shares
- `charterCapital`, `listedValue` → capital/value fields
- `freeFloatRate` → free float ratio
- `companyProfile` → HTML company description
- `address`, `website`, `telephone`, `email`, `fax` → contact fields

---

### 2.2 Get Company Leaders
**Endpoint:** `GET /company-leaderships`

**Full URL:** `https://iboard-api.ssi.com.vn/statistics/company/ssmi/company-leaderships?symbol={symbol}&language={language}&page={page}&pageSize={pageSize}`

**Description:** Retrieve company leadership / management list.

**Query Parameters:**
- `symbol` (required): Stock symbol
- `language` (optional): Language code, e.g. `vn`
- `page` (optional): Page number
- `pageSize` (optional): Records per page

**Response Format:** JSON Object (`data` is an array)
```json
{
  "code": "SUCCESS",
  "message": "Get company leadership data success",
  "data": [
    {
      "symbol": "ACB",
      "fullName": "Trần Hùng Huy",
      "positionName": "Chủ tịch Hội đồng Quản trị",
      "positionLevel": "2.1",
      "positionId": "2",
      "personId": "4324"
    }
  ],
  "paging": {
    "total": 26,
    "page": 1,
    "pageSize": 100
  },
  "status": "ok"
}
```

**Field Mapping:**
- `fullName` → leader name
- `positionName` → position title
- `positionLevel`, `positionId` → SSI position hierarchy/code
- `personId` → SSI person identifier

---

### 2.3 Get Subsidiaries / Related Companies
**Endpoint:** `GET /sub-companies`

**Full URL:** `https://iboard-api.ssi.com.vn/statistics/company/ssmi/sub-companies?symbol={symbol}&language={language}&page={page}&pageSize={pageSize}`

**Description:** Retrieve subsidiaries and related companies.

**Query Parameters:**
- `symbol` (required): Parent stock symbol
- `language` (optional): Language code
- `page` (optional): Page number
- `pageSize` (optional): Records per page

**Response Format:** JSON Object (`data` is an array)
```json
{
  "code": "SUCCESS",
  "message": "Get sub companies data success",
  "data": [
    {
      "parentSymbol": "ACB",
      "parentCompanyName": "Ngân hàng Thương mại Cổ phần Á Châu",
      "roleId": "11",
      "childSymbol": "ACBA",
      "childCompanyName": "Công ty TNHH Quản Lý Nợ Và Khai Thác Tài Sản Ngân Hàng Á Châu",
      "charterCapital": null,
      "percentage": "1",
      "roleName": "Công ty con"
    }
  ],
  "paging": {
    "total": 5,
    "page": 1,
    "pageSize": 1000
  },
  "status": "ok"
}
```

**Field Mapping:**
- `parentSymbol`, `parentCompanyName` → parent company
- `childSymbol`, `childCompanyName` → subsidiary/related company
- `roleId`, `roleName` → relationship type
- `percentage` → ownership percentage/ratio
- `charterCapital` → subsidiary charter capital

---

## 3. Financial Indicators Module

### 3.1 Get Finance Indicators
**Endpoint:** `GET /finance-indicator`

**Full URL:** `https://iboard-api.ssi.com.vn/statistics/company/ssmi/finance-indicator?symbol={symbol}&page={page}&pageSize={pageSize}`

**Description:** Retrieve financial indicators and ratios by report period.

**Query Parameters:**
- `symbol` (required): Stock symbol
- `page` (optional): Page number
- `pageSize` (optional): Records per page

**Response Format:** JSON Object (`data` is an array)
```json
{
  "code": "SUCCESS",
  "message": "Get finance indicator data success",
  "data": [
    {
      "revenue": "8904665000000",
      "profit": "4320388000000",
      "yearReport": 2026,
      "lengthReport": 1,
      "eps": "3166.811081194",
      "dilutedEPS": "3166.8082452408",
      "pe": "7.862799315",
      "roe": "0.1749605442",
      "roa": "0.0165193965",
      "grossProfitMargin": "0.6814132607",
      "netProfitMargin": "0.4675997013",
      "debtEquity": "9.4393899621",
      "pb": "1.2952039166",
      "sharesOutstanding": "5136656599",
      "bv": "19224.7720081628",
      "beta": "0.6973144247",
      "dividendYield": "0.0401606426",
      "asset": "1030900741000000",
      "marketCap": "127902749315100",
      "netProfit": null
    }
  ],
  "paging": {
    "total": 54,
    "page": 1,
    "pageSize": 10
  },
  "status": "ok"
}
```

**Field Mapping:**
- `yearReport` → report year
- `lengthReport` → report period length/quarter indicator
- `revenue`, `profit`, `netProfit`, `asset`, `marketCap` → financial values in VND-like raw units
- `eps`, `dilutedEPS` → earnings per share
- `pe`, `dilutedPe`, `pb` → valuation ratios
- `roe`, `roa`, `roic` → profitability ratios
- `grossProfitMargin`, `netProfitMargin` → margin ratios
- `debtEquity`, `debtAsset` → leverage ratios
- `quickRatio`, `currentRatio` → liquidity ratios
- `sharesOutstanding` → shares outstanding
- `bv` → book value per share
- `beta`, `dividendYield`, `npl`, `financialLeverage` → other indicators
- `ttmType` → trailing-twelve-month flag/type

---

### 3.2 Get Capital and Dividend History
**Endpoint:** `GET /cap-and-dividend`

**Full URL:** `https://iboard-api.ssi.com.vn/statistics/company/ssmi/cap-and-dividend?symbol={symbol}`

**Description:** Retrieve annual total assets, cash dividends, and owner capital history.

**Query Parameters:**
- `symbol` (required): Stock symbol

**Response Format:** JSON Object (`data` is an object)
```json
{
  "code": "SUCCESS",
  "message": "Get cap and dividend data success",
  "data": {
    "assetList": [
      {
        "year": "2025",
        "asset": "1025850127000000"
      }
    ],
    "cashDividendList": [
      {
        "year": "2024",
        "valuePershare": "1000.0"
      }
    ],
    "ownerCapitalList": [
      {
        "year": "2025",
        "ownerCapital": "94519719000000"
      }
    ]
  },
  "paging": null,
  "status": "ok"
}
```

**Field Mapping:**
- `assetList[].year` → fiscal year
- `assetList[].asset` → total assets
- `cashDividendList[].valuePershare` → cash dividend per share
- `ownerCapitalList[].ownerCapital` → owner/shareholder equity

---

## 4. Peers / Industry Module

### 4.1 Get Companies in Same Industry
**Endpoint:** `GET /company-in-same-industry`

**Full URL:** `https://iboard-api.ssi.com.vn/statistics/company/ssmi/company-in-same-industry?symbol={symbol}&language={language}&page={page}&pageSize={pageSize}`

**Description:** Retrieve industry peers/opponents for a symbol.

**Query Parameters:**
- `symbol` (required): Stock symbol
- `language` (optional): Language code
- `page` (optional): Page number
- `pageSize` (optional): Records per page

**Response Format:** JSON Object (`data` is an array)
```json
{
  "code": "SUCCESS",
  "message": "Get company in same industry data success",
  "data": [
    {
      "symbol": "BAB",
      "companyName": "Ngân hàng Thương mại Cổ phần Bắc Á",
      "currentPrice": "11100",
      "priceChange": "-100",
      "perPriceChange": "-0.01",
      "floorPrice": "10100",
      "ceilingPrice": "12300",
      "referencePrice": "11200",
      "exchange": "HNX",
      "icbLevel": "1",
      "matchVolume": "500"
    }
  ],
  "paging": {
    "total": 26,
    "page": 1,
    "pageSize": 100
  },
  "status": "ok"
}
```

**Field Mapping:**
- `symbol`, `companyName`, `exchange` → peer identity
- `currentPrice`, `referencePrice`, `floorPrice`, `ceilingPrice` → price fields
- `priceChange`, `perPriceChange` → price movement
- `matchVolume` → matched volume
- `icbLevel` → industry classification level

---

## 5. News and Events Module

### 5.1 Get Company News
**Endpoint:** `GET /company-news`

**Full URL:** `https://iboard-api.ssi.com.vn/statistics/company/ssmi/company-news?symbol={symbol}&pageSize={pageSize}&page={page}&fromDate={fromDate}&toDate={toDate}&language={language}`

**Description:** Retrieve company news within a date range.

**Query Parameters:**
- `symbol` (required): Stock symbol
- `page` (optional): Page number
- `pageSize` (optional): Records per page
- `fromDate` (optional): Start date (`DD/MM/YYYY`, URL encoded if needed)
- `toDate` (optional): End date (`DD/MM/YYYY`, URL encoded if needed)
- `language` (optional): Language code

**Response Format:** JSON Object (`data` is an array)
```json
{
  "code": "SUCCESS",
  "message": "Get company news data success",
  "data": [
    {
      "newId": "120217422",
      "symbol": "ACB",
      "title": "ACB: Báo cáo về thay đổi sở hữu của cổ đông lớn Công ty Cổ phần ICON",
      "shortContent": "Công ty Cổ phần ICON báo cáo về thay đổi sở hữu...",
      "fullContent": "<table>...</table>",
      "imageUrl": "https://cdn.fiingroup.vn/.../ACB1.png",
      "newsSource": "HOSE",
      "sourceCode": "hose",
      "newsSourceLink": "https://www.hsx.vn/vi/tin-tuc/...",
      "categoryCode": "instr",
      "createDate": "31/05/2026 22:51:51",
      "updateDate": "01/06/2026 09:00:01",
      "publicDate": "29/05/2026 17:48:00"
    }
  ],
  "paging": {
    "total": 5,
    "page": 1,
    "pageSize": 10
  },
  "status": "ok"
}
```

**Field Mapping:**
- `newId` → news ID
- `title`, `shortContent`, `fullContent` → content fields; `fullContent` may contain HTML
- `imageUrl` → thumbnail/image URL
- `newsSource`, `sourceCode`, `newsSourceLink` → source metadata
- `categoryCode` → category code
- `createDate`, `updateDate`, `publicDate` → date/time strings

---

### 5.2 Get Corporate Actions / Events
**Endpoint:** `GET /corporate-actions`

**Full URL:** `https://iboard-api.ssi.com.vn/statistics/company/ssmi/corporate-actions?pageSize={pageSize}&page={page}&language={language}&symbol={symbol}&fromDate={fromDate}&toDate={toDate}`

**Description:** Retrieve corporate actions and event disclosures within a date range.

**Query Parameters:**
- `symbol` (required): Stock symbol
- `page` (optional): Page number
- `pageSize` (optional): Records per page
- `fromDate` (optional): Start date (`DD/MM/YYYY`, URL encoded if needed)
- `toDate` (optional): End date (`DD/MM/YYYY`, URL encoded if needed)
- `language` (optional): Language code

**Response Format:** JSON Object (`data` is an array)
```json
{
  "code": "SUCCESS",
  "message": "Get corporate actions data success",
  "data": [
    {
      "symbol": "ACB",
      "eventName": "Giao dịch nội bộ: Giao dịch tổ chức",
      "exrightDate": null,
      "recordDate": null,
      "issueDate": "14/05/2026",
      "eventTitle": "ACB - Kết quả giao dịch nội bộ/CĐL",
      "publicDate": "29/05/2026",
      "exchange": "HOSE",
      "eventListCode": "DDINS",
      "value": "0",
      "ratio": "0",
      "eventDescription": "- Cá nhân/Tổ chức thực hiện giao dịch: ...",
      "eventCode": null,
      "sortExrightDate": null
    }
  ],
  "paging": {
    "totalPage": 2,
    "total": 13,
    "page": 1,
    "pageSize": 10
  },
  "status": "ok"
}
```

**Field Mapping:**
- `eventName`, `eventTitle`, `eventDescription` → event text fields; description may contain HTML line breaks
- `eventListCode`, `eventCode` → event type/code
- `exrightDate`, `recordDate`, `issueDate`, `publicDate`, `sortExrightDate` → event dates
- `value`, `ratio` → event value/ratio
- `exchange` → exchange

---

## 6. Shareholder Module

### 6.1 Get Shareholder Detail
**Endpoint:** `GET /share-holder-detail`

**Full URL:** `https://iboard-api.ssi.com.vn/statistics/company/ssmi/share-holder-detail?symbol={symbol}&language={language}&page={page}&pageSize={pageSize}`

**Description:** Retrieve detailed shareholder ownership records.

**Query Parameters:**
- `symbol` (required): Stock symbol
- `language` (optional): Language code
- `page` (optional): Page number
- `pageSize` (optional): Records per page

**Response Format:** JSON Object (`data` is an array)
```json
{
  "code": "SUCCESS",
  "message": "Get share holder detail data success",
  "data": [
    {
      "symbol": "SATHERGI",
      "name": "Sather Gate Investments Limited",
      "quantity": 193907186,
      "percentage": 0.0499,
      "publicDate": "01/04/2024",
      "ownerShipTypeCode": "NGOAI",
      "type": "C",
      "totalPage": 1,
      "totalRow": 62
    }
  ],
  "paging": {
    "total": 62,
    "page": 1,
    "pageSize": 100
  },
  "status": "ok"
}
```

**Field Mapping:**
- `symbol` → shareholder/holder code when available
- `name` → shareholder name
- `quantity` → owned shares
- `percentage` → ownership ratio
- `publicDate` → disclosure/as-of date
- `ownerShipTypeCode` → ownership type code (`NGOAI` = foreign in tested sample)
- `type` → shareholder type code
- `totalPage`, `totalRow` → duplicated pagination metadata inside each row

---

### 6.2 Get Shareholder Summary
**Endpoint:** `GET /share-holder-summary`

**Full URL:** `https://iboard-api.ssi.com.vn/statistics/company/ssmi/share-holder-summary?symbol={symbol}&language={language}`

**Description:** Retrieve high-level ownership breakdown by foreign, state, and other holders.

**Query Parameters:**
- `symbol` (required): Stock symbol
- `language` (optional): Language code

**Response Format:** JSON Object (`data` is an array)
```json
{
  "code": "SUCCESS",
  "message": "Get share holder summary data success",
  "data": [
    {
      "symbol": "ACB",
      "foreignerVolume": "1278225462",
      "foreignerPercentage": "0.24884386",
      "stateVolume": "0",
      "statePercentage": "0",
      "otherVolume": "3858431137",
      "otherPercentage": "0.75115614",
      "publicDate": "01/06/2026"
    }
  ],
  "paging": null,
  "status": "ok"
}
```

**Field Mapping:**
- `foreignerVolume`, `foreignerPercentage` → foreign ownership
- `stateVolume`, `statePercentage` → state ownership
- `otherVolume`, `otherPercentage` → other ownership
- `publicDate` → as-of date

---

## 7. Historical Stock Price Module

### 7.1 Get Stock Price History
**Endpoint:** `GET /stock-info`

**Full URL:** `https://iboard-api.ssi.com.vn/statistics/company/ssmi/stock-info?symbol={symbol}&page={page}&pageSize={pageSize}&fromDate={fromDate}&toDate={toDate}`

**Description:** Retrieve daily OHLCV and trading statistics for a symbol within a date range.

**Query Parameters:**
- `symbol` (required): Stock symbol
- `page` (optional): Page number
- `pageSize` (optional): Records per page
- `fromDate` (optional): Start date (`DD/MM/YYYY`, URL encoded if needed)
- `toDate` (optional): End date (`DD/MM/YYYY`, URL encoded if needed)

**Response Format:** JSON Object (`data` is an array)
```json
{
  "code": "SUCCESS",
  "message": "Get stock price data success",
  "data": [
    {
      "symbol": "ACB",
      "open": "24900",
      "high": "25400",
      "low": "24750",
      "close": "25100",
      "volume": "33097100",
      "tradingDate": "02/06/2026",
      "ceilingPrice": "26600",
      "floorPrice": "23200",
      "refPrice": "24900",
      "avgPrice": "25047",
      "priceChanged": "200",
      "perPriceChange": "0.8",
      "closePriceAdjusted": "25100",
      "totalMatchVol": "33097100",
      "totalMatchVal": "828970570000",
      "foreignCurrentRoom": "258395567",
      "foreignBuyVolMatched": "4373650",
      "closeRaw": "25100",
      "openRaw": "24900",
      "highRaw": "25400",
      "lowRaw": "24750"
    }
  ],
  "paging": {
    "total": 22,
    "page": 1,
    "pageSize": 10
  },
  "status": "ok"
}
```

**Field Mapping:**
- `tradingDate` → trading date (`DD/MM/YYYY`)
- `open`, `high`, `low`, `close` → OHLC prices
- `openRaw`, `highRaw`, `lowRaw`, `closeRaw` → raw OHLC prices
- `volume` → volume
- `ceilingPrice`, `floorPrice`, `refPrice`, `avgPrice` → session price references
- `priceChanged`, `perPriceChange` → price change and percent change
- `closePriceAdjusted` → adjusted close
- `totalMatchVol`, `totalMatchVal` → matched volume/value
- `totalDealVol`, `totalDealVal` → put-through/deal volume/value; can be `null`
- `foreignBuyVolTotal`, `foreignSellVolTotal`, `foreignBuyValTotal`, `foreignSellValTotal` → foreign trading totals
- `foreignBuyVolMatched`, `foreignBuyVolDeal`, `foreignCurrentRoom` → foreign matched/deal/room fields
- `totalBuyTrade`, `totalBuyTradeVol`, `totalSellTrade`, `totalSellTradeVol` → buy/sell trade statistics
- `netBuySellVol`, `netBuySellVal` → net buy/sell fields

---

## 8. Financial Statement Module

### 8.1 Get Balance Sheet
**Endpoint:** `GET /FinancialStatement/GetBalanceSheet`

**Full URL:** `https://fiin-fundamental.ssi.com.vn/FinancialStatement/GetBalanceSheet?language={language}&OrganCode={symbol}`

**Description:** Intended to retrieve a financial statement balance sheet from Fiin Fundamental.

**Query Parameters:**
- `language` (optional): Language code, e.g. `vi`
- `OrganCode` (required): Stock symbol/organization code, e.g. `ACB`

**Curl Test Result:** HTTP `403`, content type `text/html; charset=UTF-8`

**Observed Error Response:** HTML page titled `Blocked - SSI` with Cloudflare challenge script.

```html
<!doctype html>
<html lang="en">
<head>
  <title>Blocked - SSI</title>
</head>
<body>
  ... Cloudflare challenge ...
</body>
</html>
```

**Notes:**
- This endpoint did not return JSON in curl tests from this environment.
- Browser/session cookies or additional anti-bot challenge handling may be required.
- Keep implementation resilient by detecting non-JSON `403` responses before parsing.

---

## 9. Curl Test Results

| # | Name | Endpoint | HTTP | Response | Records |
|---|------|----------|------|----------|---------|
| 1 | Finance Indicator | `/finance-indicator` | `200` | JSON envelope | `data[10]` / total `54` |
| 2 | Sub Company | `/sub-companies` | `200` | JSON envelope | `data[5]` / total `5` |
| 3 | Industry Opponents | `/company-in-same-industry` | `200` | JSON envelope | `data[26]` / total `26` |
| 4 | Company Profile | `/company-profile` | `200` | JSON envelope | object |
| 5 | Company Leaders | `/company-leaderships` | `200` | JSON envelope | `data[26]` / total `26` |
| 6 | Cap & Dividend | `/cap-and-dividend` | `200` | JSON envelope | object lists |
| 7 | News | `/company-news` | `200` | JSON envelope | `data[5]` / total `5` |
| 8 | Events | `/corporate-actions` | `200` | JSON envelope | `data[10]` / total `13` |
| 9 | Balance Sheet | `/FinancialStatement/GetBalanceSheet` | `403` | HTML block page | unavailable |
| 10 | Shareholder Detail | `/share-holder-detail` | `200` | JSON envelope | `data[62]` / total `62` |
| 11 | Shareholder Summary | `/share-holder-summary` | `200` | JSON envelope | `data[1]` |
| 12 | Stock Info | `/stock-info` | `200` | JSON envelope | `data[10]` / total `22` |

---

## 10. Error Handling

**Common HTTP Status Codes Observed/Expected:**
- `200` - Success
- `403` - Forbidden / bot protection / Cloudflare challenge, observed on Fiin Fundamental balance sheet endpoint
- `400` - Bad request, likely invalid query parameters
- `404` - Not found, likely invalid endpoint
- `500` - Server error

**Recommended Handling:**
- Check HTTP status before JSON parsing.
- Check `Content-Type`; only parse JSON when it contains `application/json`.
- For iBoard JSON errors, inspect `code`, `message`, and `status`.
- Treat HTML responses from `fiin-fundamental.ssi.com.vn` as blocked/unavailable.

---

## 11. Rate Limiting

No explicit rate limits were discovered from the raw API definitions. Recommended client behavior:
- Use reasonable `pageSize` values.
- Add short delays between bulk requests.
- Cache static company profile/shareholder data.
- Retry transient failures with backoff.
- Avoid high-frequency scraping against protected Fiin Fundamental endpoints.

---

## 12. Data Normalization

### Dates
- Query date parameters use `DD/MM/YYYY` format and should be URL encoded in query strings.
- Response dates are commonly returned as `DD/MM/YYYY` or `DD/MM/YYYY HH:mm:ss`.

### Numeric Values
- Many numeric values are returned as strings, e.g. prices, VND amounts, percentages, ratios.
- Convert string fields to `BigDecimal` for monetary values and ratios.
- Share counts and volumes may be string or numeric depending on endpoint.

### HTML Content
- `companyProfile`, `fullContent`, and `eventDescription` may contain HTML.
- Strip or sanitize HTML before displaying in plain-text contexts.

---

## 13. Data Source Attribution

When using data from these endpoints, please attribute:
- **Source:** SSI iBoard / SSI Securities
- **Provider:** `iboard-api.ssi.com.vn`, `fiin-fundamental.ssi.com.vn`
- **Data Type:** Vietnamese Stock Market Company, Ownership, News, Event, and Price Data

---

*Last Tested: June 2, 2026*  
*Version: 1.0.0*
