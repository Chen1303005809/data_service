Requets:
```json
{
  "nRequestID": 1,          // [number] 请求编号
  "GlobalID": 0,            // [number] 用于区分内外盘，默认为 0
  "ExchangeID": "",         // [string] 交易所 ID，期货合约名不同可为空
  "InstrumentID": "AP8888", // [string] 合约名 (若查询主连则为品种名后加 8888)
  "CycleType": 1,           // [number] K线周期类型 (见下方枚举说明)
  "QryNum": 400,            // [number] 查询根数 (从结束日期往前取 N 根 K 线)
  "EndDate": 20260102,      // [number] 结束日期 (交易日，格式: YYYYMMDD)
  "EndTime": 0              // [number] 结束时间 (格式: HHMMSS, 24小时制, 默认0)
}
```
> 附：CycleType 枚举说明
1:分钟, 2:小时, 3:天, 4:周, 5:月, 6:5分钟, 7:3分钟, 8:6分钟, 9:10分钟, 10:15分钟, 11:30分钟, 12:季, 13:半年, 14:年



Response:
```json
{
  "Ins": "FG8888",      // [string] 合约 ID
  "Ty": 1,              // [number] CycleType (K线周期类型)
  "Req": 1,             // [number] 请求编号 (对应请求中的 nRequestID)
  "GID": 0,             // [number] 内外盘标识符
  "EID": "",            // [string] 交易所 ID
  "SD": 20260706,       // [number] 开始日期 (交易日)
  "ST": 210000,         // [number] 开始时间
  "ED": 20260706,       // [number] 结束日期 (交易日)
  "ET": 210000,         // [number] 结束时间
  
  "errinfo": {
    "EM": "",           // [string] 错误信息
    "Er": 0             // [number] 错误码 (0表示无错误，非0表示发生错误)
  },
  
  "data": [
    {
      "TiD": "20260706",  // [string] 交易日
      "TeD": "20260703",  // [string] 自然日
      "T": "21:00:00",    // [string] 该笔行情的时间
      "O": 977,           // [number] 开盘价 (Open)
      "H": 982,           // [number] 最高价 (High)
      "L": 976,           // [number] 最低价 (Low)
      "C": 980,           // [number] 收盘价 (Close)
      "OI": 1825310,      // [number] 持仓量 (Open Interest)
      "V": 61906,         // [number] 成交量 (Volume)
      "VD": 61906,        // [number] 与上一笔成交量之差 (Volume Delta)
      "A": 60605974       // [number] 成交额 (Amount)
    }
  ]
}
```