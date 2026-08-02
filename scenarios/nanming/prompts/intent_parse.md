# 南明场景领土与势力参考

## 可用领土ID

大清领地: beijing(北京/京师), shenyang(沈阳/盛京), jinan(济南), luoyang(洛阳), kaifeng(开封), datong(大同), taiyuan(太原)
南明领地: nanjing(南京/应天), yangzhou(扬州), wuchang(武昌), zhenjiang(镇江), hangzhou(杭州), xuzhou(徐州), nanchang(南昌), fuzhou(福州)
农民军领地: chengdu(成都), xiangyang(襄阳)
郑氏领地: xiamen(厦门), quanzhou(泉州), taiwan(台湾)

## 南明场景解析示例

### 示例1：农民军联明抗清
玩家指令：
```
【联明抗清】弘光帝若接纳归顺，我愿率大军出川与南明江北诸镇合兵。
命刘宗敏练兵备战，李过屯田积粮，为日后北伐做准备。
遣使联络左良玉等湖广诸将共商大计。
```

解析输出：
```json
{
  "commands": [
    {
      "type": "negotiate",
      "params": {"target_faction": "nanming", "proposal": "归顺南明，率大军出川与江北诸镇合兵抗清", "action": "form_alliance"},
      "notes": "联明抗清战略：先与南明达成归顺协议，获取合法性"
    },
    {
      "type": "move",
      "params": {"destination": "wuchang", "source_territory": "chengdu"},
      "notes": "率主力出川东进武昌，与南明左良玉等江北诸镇会师。出川=离开四川领地前往武昌，不是攻击四川"
    },
    {
      "type": "train",
      "params": {"territory": "chengdu"},
      "notes": "命刘宗敏在成都练兵备战，为日后北伐做准备"
    },
    {
      "type": "develop",
      "params": {"territory": "xiangyang"},
      "notes": "命李过在襄阳屯田积粮，保障东出大军的后勤补给"
    }
  ]
}
```

### 示例2：农民军休养生息
玩家指令：
```
【休养生息】大顺新败退守川楚。当务之急是屯田积粮、安抚流民。
命李过在四川兴修水利，牛金星在襄阳开科取士收揽人心。
减税至两成以养民力。
```

解析输出：
```json
{
  "commands": [
    {
      "type": "develop",
      "params": {"territory": "chengdu"},
      "notes": "命李过在四川兴修水利，发展农业恢复经济"
    },
    {
      "type": "develop",
      "params": {"territory": "xiangyang"},
      "notes": "命牛金星在襄阳开科取士，收揽士人之心，安定地方"
    },
    {
      "type": "tax",
      "params": {"rate": 0.2},
      "notes": "减税至两成养民力，恢复战后民生"
    },
    {
      "type": "rest",
      "params": {},
      "notes": "农民军新败后整体休整，避免立即出战"
    }
  ]
}
```
注意：文本说"退守川楚"——是防守自己的领地chengdu和xiangyang，绝不能用attack。也没有"出兵""进攻""攻打"等攻击关键词。

### 示例3：湖广会战
玩家指令：
```
【湖广会战】清军多铎部南下兵锋直指武昌！
我与左良玉合兵在襄阳武昌一线布防。
命刘宗敏率精锐三万埋伏荆山断其粮道。
遣使赴闽联络郑成功约水师北上夹击。
```

解析输出：
```json
{
  "commands": [
    {
      "type": "defend",
      "params": {"territory": "xiangyang", "unit_type": "all"},
      "notes": "湖广会战：清军多铎部南下，在襄阳部署重兵防守"
    },
    {
      "type": "defend",
      "params": {"territory": "wuchang", "unit_type": "all"},
      "notes": "湖广会战：武昌是南明江北重镇，必须守住"
    },
    {
      "type": "move",
      "params": {"destination": "wuchang", "amount": 30000, "unit_type": "elite"},
      "notes": "湖广会战：刘宗敏率三万精锐前往武昌前线，负责断清军粮道"
    },
    {
      "type": "negotiate",
      "params": {"target_faction": "zheng", "proposal": "约水师北上夹击清军多铎部", "action": "form_alliance"},
      "notes": "湖广会战配套外交：联络郑成功水师从海上牵制清军"
    }
  ]
}
```

### 示例4：南明防守
玩家指令：
```
【江北防御】清军已破洛阳，兵锋直指江淮。
在扬州部署五万守军，令史可法督师江北。
同时加固南京城防，以防不测。
```

解析输出：
```json
{
  "commands": [
    {
      "type": "defend",
      "params": {"territory": "yangzhou", "amount": 50000},
      "notes": "江北防线核心：扬州扼守运河，史可法督师防守"
    },
    {
      "type": "defend",
      "params": {"territory": "nanjing"},
      "notes": "加固南京城防，作为最后防线"
    }
  ]
}
```
