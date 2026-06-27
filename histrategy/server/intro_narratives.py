"""
Intro narratives for single-player game start.

These are used as fallback when ScenarioLoader has no intro data.
Eventually they should be moved into scenario JSON/Toml files.
"""

INTRO_NARRATIVES_EN: dict[str, str] = {
    "cao": (
        "Spring of 207 AD. Cao Cao has pacified the north, controlling the Central Plains "
        "with the Emperor as his puppet. His strategists are legion, his generals unmatched. "
        "Yet Liu Biao holds Jing Province, Sun Quan rules Jiangdong, and Liu Bei camps at "
        "Xinye — the realm remains divided. This spring, Cao Cao summons his court at Xuchang "
        "to plan the southern campaign."
    ),
    "shu": (
        "Spring of 207 AD. Liu Bei shelters in the small town of Xinye. Though his army counts "
        "barely a few thousand, his heart burns for the Han dynasty. Guan Yu, Zhang Fei, and "
        "Zhao Yun are warriors worth a thousand men each — but he lacks a strategist. Word reaches "
        "him of a genius recluse at Longzhong named Zhuge Liang. Liu Bei resolves to visit him in "
        "person — three times if necessary."
    ),
    "wu": (
        "Spring of 207 AD. Sun Quan inherited his father's and brother's legacy, ruling the six "
        "commanderies of Jiangdong. Zhang Zhao governs civil affairs, Zhou Yu commands the fleet, "
        "and the Yangtze River is his moat. But Cao Cao glares from the north and Liu Biao presses "
        "from the west. Sun Quan knows: survival requires more than defense."
    ),
    "octavian": (
        "44 BC. Julius Caesar lies dead on the Senate floor, and the Roman Republic teeters on the "
        "edge of chaos. An 18-year-old named Octavian — Caesar's adopted son and heir — crosses the "
        "Adriatic from Apollonia. He has no army, no allies, and no experience. But he has one thing "
        "more powerful than legions: the name Gaius Julius Caesar Octavianus. All of Rome watches: "
        "can this boy hold the ashes of Caesar's legacy?"
    ),
    "antony": (
        "44 BC. Caesar is dead. As his most trusted general, Mark Antony controls Rome and Caesar's "
        "legions. But the Senate despises him, Caesar's young heir Octavian challenges his authority, "
        "and the Gallic provinces are his last bargaining chip. Antony must choose: stay in Rome and "
        "risk everything, or march to Gaul and gather his forces?"
    ),
    "cleopatra": (
        "44 BC. News of Caesar's assassination reaches Alexandria. Cleopatra VII, Pharaoh of Egypt, "
        "has lost her most powerful Roman protector. She commands the richest granary in the "
        "Mediterranean — but in a world run by Roman warlords, what power does a woman truly hold? "
        "She must find a new ally among Caesar's successors, or watch Egypt be devoured."
    ),
    "senate": (
        "44 BC. Brutus and Cassius plunged their daggers into Caesar and cried 'The Republic is "
        "saved!' — but the people of Rome did not cheer. The Senate holds the eastern provinces, "
        "but Antony's legions are marching. The Republic is dying. The only question left: who will "
        "strike the final blow?"
    ),
}

INTRO_NARRATIVES_ZH: dict[str, dict[str, str]] = {
    "cao": {
        "classical": (
            "建安十二年春，曹操已平河北，拥兖豫之地，挟天子以令诸侯。帐下谋士如云，猛将如雨，"
            "然南方刘表、孙权、刘备各据州郡，天下未定。是岁，曹操于许昌大会群臣，问计于荀彧、"
            "郭嘉诸谋士。"
        ),
        "vernacular": (
            "公元207年，曹操已平定北方，坐拥中原。挟天子以令诸侯，麾下谋士如云、猛将如雨。"
            "然而南方刘表占据荆州，孙权坐断江东，刘备屯兵新野——天下一统的大业，仍前路漫漫。"
            "这一年春天，曹操在许昌大会群臣，准备迈出南下的第一步。"
        ),
    },
    "shu": {
        "classical": (
            "建安十二年春，刘备寄居新野，虽兵微将寡，然心怀汉室，志在天下。麾下关羽、张飞、"
            "赵云皆万人敌，唯缺谋主。闻隆中有贤士诸葛亮，刘备决意三顾茅庐。"
        ),
        "vernacular": (
            "公元207年，刘备寄居新野小城。虽然兵力不过数千，但他心怀汉室，志在天下。"
            "关羽、张飞、赵云皆是万人敌的猛将，但缺少一位运筹帷幄的军师。听说隆中有一位奇才"
            "诸葛亮，刘备决定亲自去拜访。"
        ),
    },
    "wu": {
        "classical": (
            "建安十二年春，孙权承父兄基业，坐领江东六郡。内有张昭、周瑜等文武之才，"
            "外有长江天险，然北有曹操虎视，西有刘表为邻，孙权日夜思量进取之策。"
        ),
        "vernacular": (
            "公元207年，孙权继承父兄的基业，统领江东六郡。文有张昭，武有周瑜，更有长江天险"
            "作为屏障。但北方的曹操虎视眈眈，西边的刘表也是一大威胁。孙权深知，偏安一隅"
            "终非长久之计。"
        ),
    },
    "octavian": {
        "classical": (
            "公元前44年，尤利乌斯·恺撒在庞培剧院遇刺身亡，罗马共和国陷入空前的权力真空。"
            "年仅18岁的屋大维被遗嘱指定为继承人，从阿波罗尼亚渡海返回意大利。他既无军队，"
            "也无政治经验，却拥有恺撒之名——这是罗马最锋利的武器。"
        ),
        "vernacular": (
            "公元前44年，恺撒遇刺，罗马陷入混乱。18岁的屋大维突然成了恺撒的继承人。"
            "他没有军队，没有盟友，只有一个名字——盖乌斯·尤利乌斯·恺撒·屋大维。"
            "整个罗马都在注视着他：这个少年能守住恺撒留下的余烬吗？"
        ),
    },
    "antony": {
        "classical": (
            "公元前44年，恺撒遇刺后，其最信任的将军马克·安东尼控制了罗马城。他手握恺撒的"
            "军团与财富，却面临元老院的敌意和恺撒继承人的挑战。高卢行省是安东尼最大的筹码"
            "——但控制高卢意味着放弃罗马。"
        ),
        "vernacular": (
            "公元前44年，恺撒死了。作为他最信任的将军，安东尼控制了罗马城和恺撒的军团。"
            "但麻烦才刚刚开始——元老院恨他，恺撒的继承人屋大维在挑战他的权威，而高卢行省"
            "是他最后的底牌。安东尼必须做出选择：留下控制罗马，还是去高卢集结军队？"
        ),
    },
    "cleopatra": {
        "classical": (
            "公元前44年，恺撒遇刺的消息传到亚历山大里亚，克利奥帕特拉七世失去了罗马最强的"
            "庇护者。作为埃及法老，她控制着罗马最重要的粮仓，却身处一个由罗马男人主导的"
            "世界。她必须在恺撒的继承者们之间，找到新的盟友。"
        ),
        "vernacular": (
            "公元前44年，恺撒死了。对克利奥帕特拉来说，这不只是失去一个情人，更是失去罗马"
            "最强的保护伞。她是埃及的法老，控制着罗马的粮仓——但在这个由罗马男人主导的世界里，"
            "一个女人如何生存？她必须在这场内战中，找到正确的那一方。"
        ),
    },
    "senate": {
        "classical": (
            "公元前44年，布鲁图斯和卡西乌斯刺杀了恺撒，高呼'共和国万岁'——却发现罗马人民并不"
            "感谢他们。元老院控制着东部行省，但安东尼的军团正在逼近。共和国已垂死，问题是："
            "谁将给它最后一击？"
        ),
        "vernacular": (
            "公元前44年，布鲁图斯和卡西乌斯刺杀了恺撒。他们以为人民会欢呼共和国的重生——"
            "但人民只是沉默。元老院控制着东部行省，但安东尼的军团正在逼近。共和国已经垂死，"
            "问题只是：谁来做最后的刽子手？"
        ),
    },
}
