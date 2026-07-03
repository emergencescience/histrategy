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
    "nanming": (
        "Spring 1645 AD. Over a year has passed since the Chongzhen Emperor hanged himself on Coal Hill. "
        "Prince Fu has ascended the throne in Nanjing as the Hongguang Emperor. Yet factional strife "
        "tears at the court, the four northern garrisons plot their own ambitions, and Qing forces "
        "occupying Beijing prepare to march south. Shi Kefa commands the defense at Yangzhou — a lone "
        "pillar. The Southern Ming still holds half the empire, but division and distrust gnaw at its "
        "foundations."
    ),
    "qing": (
        "Spring 1645 AD. Regent Dorgon governs from Beijing. The Eight Banners now control Zhili, "
        "Shanxi, Shaanxi, and Shandong. Wu Sangui's elite Shanhai Pass garrison has pledged "
        "allegiance to the Qing, becoming the vanguard for the southern campaign. Yet Ming remnants "
        "regroup in Nanjing, Li Zicheng's peasant army still operates in Sichuan, and the wealthy "
        "Jiangnan region remains unconquered. Half the empire is won — but the road to unification "
        "stretches long."
    ),
    "nongminjun": (
        "Spring 1645 AD. Li Zicheng's Shun dynasty has retreated into Sichuan. Beijing was taken "
        "and lost; Qing forces flood into the Central Plains like a tide. The once-mighty peasant army "
        "is reduced to remnants, struggling to unite Zhang Xianzhong's old turf with Li Zicheng's "
        "survivors. The Tibetan Plateau to the west, the Southern Ming to the south, the Qing to "
        "the north — survival is the first priority."
    ),
    "zheng": (
        "Spring 1645 AD. Zheng Zhilong controls the coasts of Fujian and Guangdong. He commands East "
        "Asia's most powerful maritime force — the Zheng merchant fleet boasts over a thousand warships "
        "and trading vessels, monopolizing sea trade between China, Japan, and Southeast Asia. But the "
        "flames of war in the north will eventually reach the south. Zheng Zhilong faces a choice: "
        "remain the overlord of the seas, or enter the game of continental power?"
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
    "nanming": {
        "classical": (
            "弘光元年春，崇祯帝殉国已逾一载。福王朱由崧即位于南京，改元弘光。然朝中党争未息，"
            "江北四镇各怀异志，多尔衮坐镇北京，虎视江南。史可法督师扬州，独力难支。"
            "南明虽据半壁江山，然内忧甚于外患。"
        ),
        "vernacular": (
            "公元1645年春，崇祯帝自缢煤山已逾一年。福王朱由崧在南京即位，建立弘光朝廷。"
            "然而朝中党争不休，江北四镇各怀异心，清军已占据北京，正虎视眈眈准备南下。"
            "史可法督师扬州，独木难支。南明尚有半壁江山，但分裂与内耗如蛆附骨。"
        ),
    },
    "qing": {
        "classical": (
            "顺治二年春，摄政王多尔衮坐镇北京。八旗劲旅已控直隶、山西、陕西、山东诸省。"
            "吴三桂率关宁铁骑归附清朝，为南下先锋。然明室余烬未灭，李闯残部盘踞四川，"
            "江南富庶之地尚未臣服。天下一统，前路仍远。"
        ),
        "vernacular": (
            "公元1645年春，摄政王多尔衮坐镇北京。八旗劲旅已控制北直隶、山西、陕西和山东。"
            "吴三桂的山海关精锐归附清朝，成为南下先锋。然而明朝残余在南京重组，李自成的"
            "农民军仍在四川活动，江南富庶之地尚未臣服。天下已得一半，但统一之路仍漫长。"
        ),
    },
    "nongminjun": {
        "classical": (
            "弘光元年春，大顺军退守四川。北京得而复失，清军如潮水涌入中原。百万义军仅余残部，"
            "李自成与张献忠旧部艰难整合。西有藏地，南有明室，北有清虏——生存乃第一要务。"
        ),
        "vernacular": (
            "公元1645年春，李自成的大顺政权已退入四川。北京得而复失，清军如潮水般涌入中原。"
            "曾经的百万农民军如今只剩残部，在张献忠的旧地与李自成的余部之间艰难整合。"
            "西有青藏高原，南有南明，北有清军——生存是第一要务。"
        ),
    },
    "zheng": {
        "classical": (
            "弘光元年春，郑芝龙掌控闽粤沿海。郑氏商团坐拥千艘战船商舶，垄断中日与南洋之海上"
            "贸易，为东亚最强海上势力。然北方战火迟早蔓延至南。郑芝龙面临抉择——"
            "继续做海上霸主，抑或介入大陆权力之争？"
        ),
        "vernacular": (
            "公元1645年春，郑芝龙控制着福建和广东沿海。他是东亚最强大的海上力量——"
            "郑氏商团拥有上千艘战船和商船，垄断着中国与日本、东南亚的海上贸易。"
            "但北方的战火迟早会蔓延到南方。郑芝龙面临抉择：继续做海上霸主，还是介入大陆的"
            "权力游戏？"
        ),
    }
}
