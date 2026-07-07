"""
Engine helper functions and constants extracted from game.py.

Contains:
  - FIRST_TURN_SUGGESTIONS
  - create_initial_world()
  - _suppress_stderr()
  - _inject_v3_into_baseline()
  - _auto_mobilize_for_attack()
  - _build_faction_id_map()
  - _build_territory_id_map()
  - apply_event_effects()
"""

from __future__ import annotations

import os

# ─── v2 engine (always available) ────────────────────────────────
from histrategy_engine import (  # noqa: E402
    WorldState as V2WorldState,
)

from ..state.world_state import (  # noqa: E402
    FactionState,
    WorldState,
    save_world,
)
from .faction_slot import FACTION_LEGACY_MAP as V2_FACTION_MAP  # noqa: F401 — backward compat

# ─── Macro engine: early-turn hard-coded suggestions ────────────
# Per-scenario, per-faction, per-turn (1-4), per-locale (zh/en).
# Turns 1-4 use deterministic suggestions to avoid LLM latency.
# Turn 5+ falls back to heuristic (build_strategic_suggestions).

EARLY_TURNS_SUGGESTIONS = {
    "three-kingdoms": {
        "cao": {
            1: {
                "zh": [
                    "【南征荆州】整编水师于邺城玄武池，命于禁毛玠督练，准备南征刘表",
                    "【安抚河北】降低冀州税率至20%，安抚新附之民，巩固河北后方",
                    "【屯田许昌】在许昌周边推行军屯，储备南征粮草",
                    "【劝降孙权】遣使赴江东，以朝廷名义封孙权为讨虏将军，试探其意",
                ],
                "en": [
                    "【Southern Campaign】Drill the navy at Xuanwu Lake, prepare to march on Jing Province",
                    "【Pacify Hebei】Lower tax rates to appease newly conquered northern provinces",
                    "【Garrison Farms】Establish military farms near Xuchang to stockpile provisions",
                    "【Envoy to Wu】Send an imperial decree to Sun Quan, offering titles to test his loyalty",
                ],
            },
            2: {
                "zh": [
                    "【整军备战】在许昌集结主力，于禁乐进各统一军准备南征",
                    "【分化诸侯】遣使赴益州刘璋，示以朝廷威德，劝其归附",
                    "【肃清谍网】命校事府彻查江东细作，清剿内部谍报网",
                    "【文学兴盛】在邺城举办文学盛会，招揽天下文人以壮声势",
                ],
                "en": [
                    "【Mobilize Forces】Assemble the main army at Xuchang for the southern expedition",
                    "【Divide the Vassals】Send envoys to Liu Zhang in Yi Province to demand submission",
                    "【Purge Spies】Order the secret police to root out Wu intelligence networks",
                    "【Literary Patronage】Host literary gatherings at Ye to attract scholar talent",
                ],
            },
            3: {
                "zh": [
                    "【南征先锋】命曹仁为先锋，率精骑五千先行进驻宛城",
                    "【水军提速】加紧玄武池水军训练，限期三月成军",
                    "【策反荆州】密遣细作赴襄阳，联络蔡瑁张允以为内应",
                    "【威震关中】命夏侯渊巡视长安，安抚凉州诸羌",
                ],
                "en": [
                    "【Vanguard South】Dispatch Cao Ren with 5,000 elite cavalry to Wancheng",
                    "【Navy Sprint】Accelerate naval training — deadline three months to readiness",
                    "【Subvert Jing】Send covert agents to Xiangyang to recruit Cai Mao as an inside ally",
                    "【Overawe the West】Have Xiahou Yuan patrol Chang'an and pacify the Qiang tribes",
                ],
            },
            4: {
                "zh": [
                    "【主力南下】曹操亲率大军二十万从许昌出发，天下震动",
                    "【檄文讨逆】发布讨逆檄文，斥刘备孙权为叛臣，号召天下共讨",
                    "【后勤保障】命程昱督运粮草，确保大军补给线通畅",
                    "【安抚朝臣】在出征前安抚汉献帝及朝中大臣，防止后方生变",
                ],
                "en": [
                    "【March South】Cao Cao personally leads 200,000 troops from Xuchang — the realm trembles",
                    "【Proclamation】Issue a denunciation of Liu Bei and Sun Quan as traitors to the Han",
                    "【Supply Lines】Appoint Cheng Yu to oversee logistics along the march route",
                    "【Secure the Court】Pacify Emperor Xian and the court ministers before departure",
                ],
            },
        },
        "shu": {
            1: {
                "zh": [
                    "【隆中对策】与诸葛亮商议天下三分之策，制定联吴抗曹战略",
                    "【练兵新野】在新野招募训练新兵，扩充军力以备不时之需",
                    "【结好刘表】遣简雍赴襄阳，以宗室之谊请求刘表支援粮草军械",
                    "【北境设防】命赵云巡视新野北境，设烽火台警戒宛城曹军动向",
                ],
                "en": [
                    "【Longzhong Plan】Consult Zhuge Liang on the Three-Way Division strategy against Cao Cao",
                    "【Drill at Xinye】Recruit and train new soldiers to strengthen the army",
                    "【Befriend Liu Biao】Send Jian Yong to Xiangyang to request supplies as fellow Han kinsmen",
                    "【Northern Watch】Order Zhao Yun to patrol Xinye's northern border and set up beacon towers",
                ],
            },
            2: {
                "zh": [
                    "【招揽人才】命诸葛亮举荐荆州贤才，徐庶马良等入幕",
                    "【扩充军备】在新野周边招募义勇，打造兵器铠甲",
                    "【外交孙权】遣诸葛亮携关羽赴江东，试探孙权联刘抗曹之意",
                    "【安抚百姓】降低新野税率，开仓赈济流民，收拢民心",
                ],
                "en": [
                    "【Recruit Talent】Have Zhuge Liang recommend Jing Province scholars to join the staff",
                    "【Expand Arsenal】Recruit volunteers around Xinye, forge weapons and armor",
                    "【Diplomatic Mission】Send Zhuge Liang to Jiangdong to propose an anti-Cao alliance",
                    "【Welfare Relief】Lower taxes and open granaries to refugees to win popular support",
                ],
            },
            3: {
                "zh": [
                    "【南迁准备】预判曹操南下在即，与诸葛亮商议撤退襄阳方案",
                    "【联吴定策】正式遣诸葛亮赴柴桑，向孙权陈述利害，促成孙刘联盟",
                    "【收编刘琦】联络江夏公子刘琦，争取收编其麾下水军",
                    "【撤离新野】组织新野百姓南迁，避免曹军屠戮",
                ],
                "en": [
                    "【Evacuation Plan】Anticipate Cao Cao's southern march — plan withdrawal to Xiangyang",
                    "【Forge Alliance】Send Zhuge Liang to Chaisang to convince Sun Quan of the alliance",
                    "【Absorb Liu Qi】Contact Prince Liu Qi at Jiangxia to integrate his naval forces",
                    "【Civilian Evacuation】Organize the people of Xinye to retreat south ahead of Cao's army",
                ],
            },
            4: {
                "zh": [
                    "【赤壁前夜】与周瑜会师，准备在赤壁迎击曹操水陆大军",
                    "【火攻筹备】命诸葛亮观察气象，选择火攻最佳时机",
                    "【水军整合】将收编的荆州水军与江东水军合并训练",
                    "【坚壁清野】在江北实施坚壁清野，断曹军就地补给",
                ],
                "en": [
                    "【Eve of Red Cliffs】Link up with Zhou Yu, prepare to confront Cao Cao at Red Cliffs",
                    "【Fire Attack】Have Zhuge Liang study the weather for the optimal fire attack window",
                    "【Naval Integration】Merge captured Jing naval forces with Wu's fleet for joint training",
                    "【Scorched Earth】Deny Cao Cao's army local supplies north of the river",
                ],
            },
        },
        "wu": {
            1: {
                "zh": [
                    "【水军扩建】命周瑜在鄱阳湖大造战船，扩编水军至三万",
                    "【稳定山越】派程普鲁肃安抚山越诸部，巩固江东后方",
                    "【联刘抗曹】遣鲁肃赴新野，以吊刘表之名探刘备虚实，商议联盟",
                    "【发展江东】降低吴郡会稽税率，鼓励农商，充实府库",
                ],
                "en": [
                    "【Expand Navy】Order Zhou Yu to construct warships at Poyang Lake, grow the fleet to 30,000",
                    "【Pacify Shanyue】Send Cheng Pu and Lu Su to settle the Shanyue tribes in the hinterlands",
                    "【Scout Liu Bei】Dispatch Lu Su to Xinye under the pretext of condolences to assess Liu Bei",
                    "【Develop Jiangdong】Lower taxes in Wu and Kuaiji to promote commerce and agriculture",
                ],
            },
            2: {
                "zh": [
                    "【西讨黄祖】命周瑜率水军西进，讨伐江夏黄祖，打通长江上游",
                    "【延揽贤才】在吴郡设招贤馆，广纳中原南渡士人",
                    "【建造要塞】在柴桑修筑水寨，作为西进和北防的军事枢纽",
                    "【联姻荆州】试探与刘表联姻以对抗曹操北来之势",
                ],
                "en": [
                    "【Strike Huang Zu】Order Zhou Yu's fleet west to attack Jiangxia and secure the upper Yangtze",
                    "【Recruit Scholars】Open a talent hall at Wu Commandery for northern scholar-refugees",
                    "【Fortify Chaisang】Build a naval fortress as the strategic hub for westward expansion",
                    "【Marriage Diplomacy】Probe Liu Biao for a marriage alliance against Cao Cao",
                ],
            },
            3: {
                "zh": [
                    "【赤壁防线】命周瑜程普率主力水军进抵赤壁，建立沿江防线",
                    "【联刘定盟】正式与刘备结盟，约定共击曹操，胜后荆州归刘",
                    "【粮草囤积】在柴桑芜湖囤积大军粮草，准备长期作战",
                    "【激励将士】孙权亲临柴桑劳军，斩杀案几以示抗曹决心",
                ],
                "en": [
                    "【Red Cliffs Line】Deploy Zhou Yu and Cheng Pu's main fleet to Red Cliffs",
                    "【Seal Alliance】Formally ally with Liu Bei — promise Jing Province in exchange for joint victory",
                    "【Stockpile Supplies】Accumulate grain at Chaisang and Wuhu for a prolonged campaign",
                    "【Rally Troops】Sun Quan visits Chaisang personally, cuts a table corner to show resolve",
                ],
            },
            4: {
                "zh": [
                    "【火攻曹操】周瑜黄盖定下苦肉计，准备火攻曹操连环战船",
                    "【东风借箭】与诸葛亮配合，利用东南风实施火攻计划",
                    "【分兵阻击】命吕蒙率偏师阻击曹军可能从陆路南下的援军",
                    "【战后布局】预先派遣鲁肃赴南郡，准备赤壁战后抢占荆州要地",
                ],
                "en": [
                    "【Fire Ships】Zhou Yu and Huang Gai prepare the self-sacrifice ruse to ignite Cao's chained fleet",
                    "【East Wind】Coordinate with Zhuge Liang to exploit the seasonal wind for the fire attack",
                    "【Block Reinforcements】Order Lü Meng to intercept possible overland Cao reinforcements",
                    "【Post-Battle Plan】Pre-deploy Lu Su to Nan Commandery to seize Jing after Red Cliffs",
                ],
            },
        },
    },
    "rome-triumvirate": {
        "octavian": {
            1: {
                "zh": [
                    "【征召旧部】召回高卢时期的老兵，组建属于你的嫡系军团",
                    "【发表演说】前往元老院宣读遗嘱，争取温和派元老的支持",
                    "【密会强敌】拜访执政官安东尼，要求其归还恺撒的遗产",
                ],
                "en": [
                    "【Rally Veterans】Recall Caesar's Gallic War veterans to form your personal legions",
                    "【Senate Speech】Address the Senate, read Caesar's will, and court the moderates",
                    "【Confront Antony】Meet with Consul Mark Antony to demand Caesar's inheritance",
                ],
            },
            2: {
                "zh": [
                    "【招募军团】在坎帕尼亚招募新兵，扩编至五个军团",
                    "【拉拢西塞罗】与元老院领袖西塞罗建立政治同盟",
                    "【舆论造势】在罗马广场散发传单，宣扬你是恺撒的合法继承人",
                ],
                "en": [
                    "【Raise Legions】Recruit in Campania, expand to five legions",
                    "【Court Cicero】Build a political alliance with the Senate's leading orator",
                    "【Shape Opinion】Distribute pamphlets in the Forum declaring you Caesar's true heir",
                ],
            },
            3: {
                "zh": [
                    "【北进高卢】率军团北上，争取山南高卢行省总督支持",
                    "【元老院授职】请求元老院授予你代行执政官权力（Imperium）",
                    "【离间分化】散布安东尼与埃及不清不楚的传言，削弱其合法性",
                ],
                "en": [
                    "【March North】Lead legions to Cisalpine Gaul, seek the governor's allegiance",
                    "【Seek Imperium】Petition the Senate for pro-praetorian authority",
                    "【Divide and Conquer】Spread rumors of Antony's Egyptian entanglements",
                ],
            },
            4: {
                "zh": [
                    "【穆提纳之战】联合元老院军团围攻穆提纳，驱逐安东尼",
                    "【进军罗马】以胜利者姿态率军南下，要求元老院选举你为执政官",
                    "【后三头结盟】在博洛尼亚与安东尼、雷必达会盟，瓜分罗马天下",
                ],
                "en": [
                    "【Mutina Campaign】Besiege Mutina with Senate forces, drive Antony out of Italy",
                    "【March on Rome】Lead victorious legions south, demand election as consul",
                    "【Second Triumvirate】Meet Antony and Lepidus at Bononia — divide the Roman world",
                ],
            },
        },
        "antony": {
            1: {
                "zh": [
                    "【稳固罗马】作为执政官掌控罗马城，调动恺撒国库充实军备",
                    "【安抚军队】赏赐恺撒老兵每人500银币，稳固军心",
                    "【西讨庞培】派兵清剿西西里的塞克斯图斯·庞培残余舰队",
                ],
                "en": [
                    "【Secure Rome】As consul, control the city and tap Caesar's treasury for the army",
                    "【Reward Veterans】Grant 500 denarii per soldier to lock in Caesar's veteran loyalty",
                    "【Hunt Pompey】Send forces to clear Sextus Pompey's remnants from Sicily",
                ],
            },
            2: {
                "zh": [
                    "【北进高卢】率两个军团北上，收编山南高卢及纳尔榜高卢行省",
                    "【整顿吏治】更换各行省总督，安插自己的亲信控制税收",
                    "【外交埃及】加强与克利奥帕特拉的联系，确保东部粮食供应",
                ],
                "en": [
                    "【Move North】March two legions into Gaul, absorb Cisalpine and Narbonensis provinces",
                    "【Purge Governors】Replace provincial governors with loyal appointees to control tax revenue",
                    "【Egyptian Ties】Strengthen relations with Cleopatra to secure eastern grain shipments",
                ],
            },
            3: {
                "zh": [
                    "【对抗元老院】宣布元老院为非法，要求屋大维交出非法征募的军团",
                    "【围攻穆提纳】率军包围穆提纳城，逼迫元老院军投降",
                    "【东方战略】向马其顿方向扩展，建立东方势力范围",
                ],
                "en": [
                    "【Defy the Senate】Declare the Senate's decrees invalid, demand Octavian disband his legions",
                    "【Siege Mutina】Encircle Mutina and force the Senate's legions to capitulate",
                    "【Eastern Strategy】Expand influence eastward toward Macedonia",
                ],
            },
            4: {
                "zh": [
                    "【战略撤退】若战不利则退入纳尔榜高卢，保存主力",
                    "【后三头会盟】接受雷必达调解，在博洛尼亚与屋大维谈判分权",
                    "【分配东方】争取分得东方富庶行省，建立自己的王国",
                ],
                "en": [
                    "【Strategic Retreat】If pressed, withdraw to Narbonensis to preserve the army",
                    "【Triumvirate Talks】Accept Lepidus' mediation, negotiate power-sharing with Octavian at Bononia",
                    "【Claim the East】Secure the wealthy eastern provinces as your domain",
                ],
            },
        },
        "cleopatra": {
            1: {
                "zh": [
                    "【巩固埃及】巡视亚历山大里亚和昔兰尼加，整饬内政",
                    "【扩建海军】在塞浦路斯和亚历山大里亚扩建舰队保护贸易",
                    "【联络安东尼】派遣使节携带尼罗河礼物前往罗马会见安东尼",
                ],
                "en": [
                    "【Consolidate Egypt】Tour Alexandria and Cyrenaica, reform domestic administration",
                    "【Expand Fleet】Build warships in Cyprus and Alexandria to protect trade routes",
                    "【Gifts to Antony】Send emissaries with Nile treasures to meet Mark Antony in Rome",
                ],
            },
            2: {
                "zh": [
                    "【粮食外交】以埃及谷物为筹码，向饥荒中的罗马城施以恩惠",
                    "【建设亚历山大里亚】投资图书馆和博物馆，打造地中海文化中心",
                    "【塞浦路斯治理】派遣总督治理塞浦路斯，垄断东地中海铜矿贸易",
                ],
                "en": [
                    "【Grain Diplomacy】Use Egyptian grain as leverage — feed starving Rome, earn its gratitude",
                    "【Build Alexandria】Invest in the Library and Museum, make Alexandria the cultural capital",
                    "【Cyprus Administration】Appoint a governor to Cyprus, monopolize eastern copper trade",
                ],
            },
            3: {
                "zh": [
                    "【支持安东尼】提供战舰和资金支持安东尼的军事行动，换取东地中海霸权",
                    "【南方远征】派遣远征军沿尼罗河南下，探索上埃及金矿",
                    "【离间分化】在安东尼与屋大维之间保持平衡，确保埃及安全",
                ],
                "en": [
                    "【Back Antony】Supply ships and funds for Antony's campaigns in exchange for eastern hegemony",
                    "【Southern Expedition】Send scouts up the Nile to explore Upper Egyptian gold mines",
                    "【Balance of Power】Play Antony and Octavian against each other to keep Egypt safe",
                ],
            },
            4: {
                "zh": [
                    "【东方王国】与安东尼达成协定，将东地中海划为埃及势力范围",
                    "【海军称霸】组建东地中海最强大的舰队，控制海上贸易",
                    "【王国联姻】考虑与安东尼建立更紧密的王朝联姻关系",
                ],
                "en": [
                    "【Eastern Dominion】Negotiate with Antony to carve out an eastern sphere for Egypt",
                    "【Naval Supremacy】Build the most powerful fleet in the eastern Mediterranean",
                    "【Dynastic Union】Consider a royal marriage alliance with Mark Antony",
                ],
            },
        },
        "senate": {
            1: {
                "zh": [
                    "【维护共和】在元老院发表捍卫共和制度的演说，反对军人独裁",
                    "【收编军团】整合伊利里亚和美索不达米亚的驻军，编入元老院直属军团",
                    "【孤立安东尼】动员元老院宣布安东尼为国家公敌（Hostis）",
                ],
                "en": [
                    "【Defend the Republic】Deliver a speech in the Senate defending the Republic against military tyranny",
                    "【Consolidate Legions】Integrate the Illyrian and Mesopotamian garrisons under Senate command",
                    "【Isolate Antony】Mobilize the Senate to declare Antony a public enemy (Hostis)",
                ],
            },
            2: {
                "zh": [
                    "【拉拢屋大维】承认屋大维为恺撒的合法继承人，利用他对抗安东尼",
                    "【重建军制】任命元老院派的将领统率各军团，防止军人干政",
                    "【财政整顿】清查恺撒、安东尼侵占的公款，追回国库资金",
                ],
                "en": [
                    "【Court Octavian】Recognize Octavian as Caesar's legitimate heir to use him against Antony",
                    "【Military Reform】Appoint senatorial commanders to prevent military interference in politics",
                    "【Financial Audit】Investigate Caesar and Antony's embezzlement, recover public funds",
                ],
            },
            3: {
                "zh": [
                    "【授权讨逆】授予屋大维代行执政官权力，命其率军讨伐安东尼",
                    "【巩固东方】派遣使节安抚叙利亚和亚细亚行省，防止东方叛乱",
                    "【外交希腊】拉拢希腊各城邦，在东西方之间建立缓冲地带",
                ],
                "en": [
                    "【Grant Imperium】Award Octavian pro-praetorian authority to march against Antony",
                    "【Secure the East】Send envoys to pacify Syria and Asia, prevent eastern rebellion",
                    "【Greek Diplomacy】Court the Greek city-states as a buffer between east and west",
                ],
            },
            4: {
                "zh": [
                    "【穆提纳战役】派遣执政官率元老院军团北上，与屋大维合击安东尼",
                    "【战后清算】击败安东尼后清算其党羽，恢复元老院的绝对权威",
                    "【三头博弈】警惕屋大维势力膨胀——共和国不能以新暴君取代旧暴君",
                ],
                "en": [
                    "【Battle of Mutina】Dispatch consular legions north to join Octavian against Antony",
                    "【Post-War Purge】After defeating Antony, purge his allies and restore Senate supremacy",
                    "【Three-Way Game】Beware Octavian's growing power — the Republic cannot trade one tyrant for another",
                ],
            },
        },
    },
    "nanming": {
        "nanming": {
            1: {
                "zh": [
                    "[nanming_t1_defend]【🛡️ 整合四镇·守江先守淮】\n军事：收江北四镇兵权归史可法统一节制，重兵扼守淮河一线（守江必守淮）\n外交：遣使稳住郑氏与大顺，避免两线受敌\n内政：弭马士英史可法党争，一切以御清为先；减江南赋税三成收士心\n生产：疏浚运河确保粮饷北运，南京设军器局量产火器",
                    "[nanming_t1_ally]【⚔️ 联寇联郑·共御强清】（翻盘首选）\n军事：四镇归史可法统一号令，主力北进死守淮河，黄得功出河南牵制\n外交：放下弑君之仇，急册封李自成为秦王联闯；许郑芝龙海防重任换水师入江\n内政：弭朝中党争，量产火器武装各镇\n生产：征民兵三万充淮防，江南加紧屯田",
                    "[nanming_t1_retreat]【🏃 南迁避战】\n军事：四镇断后掩护朝廷南撤至浙江\n外交：与郑芝龙密约，郑氏水师接应南迁\n内政：转移国库金银至福州，焚毁机密文书\n生产：烧毁江北粮仓，坚壁清野不给清军补给",
                ],
                "en": [
                    "[nanming_t1_defend]【🛡️ Unify the Garrisons · Hold the Huai】\nMilitary: Strip the Four Garrisons' autonomy under Shi Kefa's unified command; hold the Huai River line first\nDiplomacy: Stabilize Zheng and the Shun remnants to avoid a two-front war\nDomestic: End Ma-Shi factionalism; cut Jiangnan taxes 30% to win hearts\nProduction: Clear the Grand Canal, Nanjing armory mass-produces firearms",
                    "[nanming_t1_ally]【⚔️ Ally Shun & Zheng · Hold the Huai】(Best turnaround)\nMilitary: Unify the Four Garrisons under Shi Kefa; hold the Huai River line (to hold the Yangtze, hold the Huai)\nDiplomacy: Set aside the regicide grudge — invest Li Zicheng as Prince of Qin; grant Zheng Zhilong naval command for a fleet on the Yangtze\nDomestic: End court factionalism, mass-produce firearms\nProduction: 30,000 militia for the Huai defense, expand farms",
                    "[nanming_t1_retreat]【🏃 Evacuate South】\nMilitary: Four Garrisons cover the court's retreat to Zhejiang\nDiplomacy: Secret pact with Zheng Zhilong for evacuation\nDomestic: Transfer imperial treasury to Fuzhou\nProduction: Scorch northern granaries — leave nothing for Qing",
                ],
            },
            2: {
                "zh": [
                    "[nanming_t2_counter]【⚔️ 联军反攻山东】\n军事：趁清军立足未稳，四镇联军配合大顺东出，黄得功刘良佐反攻济南\n外交：以海防总兵衔换郑氏水师沿海策应，约大顺牵制清军后路\n内政：江西湖广推行屯田制保障军粮\n生产：南京军器局加班赶造火炮鸟铳",
                    "[nanming_t2_hold]【🤝 联盟成型·坚守淮扬】（翻盘首选）\n军事：史可法督师，四镇归一指挥，加固淮河-扬州-南京纵深防线\n外交：正式册封李自成为秦王，联闯抗清同盟成立；郑氏水师入长江策应\n内政：遣重臣赴武昌安抚左良玉，严防其借'清君侧'东下作乱\n生产：征江南商船组建长江水师，封锁渡口",
                    "[nanming_t2_relocate]【🏰 迁都备战】\n军事：四镇精锐护送弘光帝迁都福州\n外交：请郑芝龙水师封锁长江口阻止清军水师南下\n内政：在福州建立战时内阁，重组六部\n生产：转移江南军器局设备至福建，建立南方军工基地",
                ],
                "en": [
                    "[nanming_t2_counter]【⚔️ Counterattack Shandong】\nMilitary: Huang Degong and Liu Liangzuo strike north\nDiplomacy: Offer Zheng Zhilong the admiralty for coordination\nDomestic: Military farms in Jiangxi and Huguang for food\nProduction: Nanjing armory works double shifts on cannons",
                    "[nanming_t2_hold]【🤝 Alliance Forged · Hold Huai-Yang】(Best turnaround)\nMilitary: Shi Kefa unifies the Garrisons; deep Huai-Yangzhou-Nanjing defense\nDiplomacy: Formally invest Li Zicheng as Prince of Qin; Zheng fleet enters the Yangtze\nDomestic: Send a heavyweight to Wuchang to keep Zuo Liangyu from rebelling ('clearing the ruler's side')\nProduction: Merchant ships into a Yangtze fleet, blockade the fords",
                    "[nanming_t2_relocate]【🏰 Relocate and Prepare】\nMilitary: Elite troops escort the Emperor to Fuzhou\nDiplomacy: Zheng Zhilong blockades the Yangtze mouth\nDomestic: Establish wartime cabinet in Fuzhou\nProduction: Move Nanjing armory to Fujian — southern industry",
                ],
            },
            3: {
                "zh": [
                    "[nanming_t3_laststand]【⚔️ 扬州决死】\n军事：史可法率扬州军民死守，血书求援各镇\n外交：急诏郑芝龙水师溯江而上截击清军渡江船队\n内政：弘光帝下罪己诏激励士气，赦免江北逃兵\n生产：扬州城内实行配给制，拆民房取砖石加固城墙",
                    "[nanming_t3_peace]【🕊️ 割地求和】\n军事：放弃江北四郡退守长江南岸，保留有生力量\n外交：遣重臣赴多铎大营，以称臣纳贡割山东河南换和平\n内政：安抚江南士绅，保证不增税不征兵\n生产：将江北粮草物资火速运往江南",
                    "[nanming_t3_totalwar]【🔥 全民皆兵】\n军事：在南京及江南各府发动民兵，老幼妇孺皆参与城防\n外交：以保华夏衣冠为号召，向朝鲜日本求援\n内政：没收贪官资产充军，马士英捐俸以示表率\n生产：铁匠铺改铸兵器，寺庙铜钟熔铸火炮",
                ],
                "en": [
                    "[nanming_t3_laststand]【⚔️ Last Stand at Yangzhou】\nMilitary: Shi Kefa defends to the death — blood letters for reinforcements\nDiplomacy: Urgent edict to Zheng Zhilong — sail up the Yangtze\nDomestic: Emperor issues an edict of self-blame\nProduction: Rationing in Yangzhou — tear down houses for stone",
                    "[nanming_t3_peace]【🕊️ Negotiate Peace】\nMilitary: Abandon northern prefectures, retreat behind Yangtze\nDiplomacy: Send minister to Dodo — vassalage and tribute for peace\nDomestic: Promise Jiangnan gentry no new taxes or conscription\nProduction: Evacuate all grain north of the river",
                    "[nanming_t3_totalwar]【🔥 Total War】\nMilitary: Mobilize militia across Nanjing and Jiangnan\nDiplomacy: Appeal to Korea and Japan for aid\nDomestic: Confiscate corrupt officials' assets for war\nProduction: Smithies forge weapons, temple bells into cannons",
                ],
            },
            4: {
                "zh": [
                    "[nanming_t4_sail]【⛵ 渡海投郑】\n军事：残部由浙江出海投奔郑芝龙，保存抗清火种\n外交：尊郑芝龙为太师，换取郑氏全力支持复国\n内政：在厦门设流亡朝廷，号召海外华人捐助抗清\n生产：利用郑氏贸易网络采购日本倭刀和荷兰火炮",
                    "[nanming_t4_unite]【🤝 联合大顺·据江图存】（南北朝格局）\n军事：与大顺残部会师，据长江-湖广防线持久抗清，仿东晋南宋划江而治\n外交：册封闯部将领为侯爵，联郑氏水师控扼长江，共尊正统\n内政：湖广推行均田免赋收拢流民，重建战时中枢\n生产：依托江南财赋与郑氏海贸重整军工",
                    "[nanming_t4_fight]【💀 决一死战】\n军事：集结所有兵力于南京城下，与清军主力决战\n外交：向天下发布衣冠存亡檄，号召所有汉人起兵\n内政：弘光帝御驾亲征，不成功便成仁\n生产：城中所有工匠日夜赶制守城器械和火药",
                ],
                "en": [
                    "[nanming_t4_sail]【⛵ Sail to the Zhengs】\nMilitary: Remnant forces escape by sea to join Zheng Zhilong\nDiplomacy: Honor Zheng Zhilong as Grand Tutor for full support\nDomestic: Government-in-exile in Xiamen, appeal to overseas Chinese\nProduction: Use Zheng's trade network for Japanese swords and Dutch cannons",
                    "[nanming_t4_unite]【🤝 Unite the Shun · Hold the River】(A Southern Dynasties survival)\nMilitary: Link with Shun remnants; hold the Yangtze-Huguang line for protracted war, as the Eastern Jin and Southern Song divided the realm at the river\nDiplomacy: Ennoble Shun generals; Zheng fleet controls the Yangtze under the legitimate throne\nDomestic: Land reform in Huguang; rebuild a wartime court\nProduction: Rebuild arms on Jiangnan taxes and Zheng maritime trade",
                    "[nanming_t4_fight]【💀 Fight to the Death】\nMilitary: Gather every soldier at Nanjing for a decisive battle\nDiplomacy: Proclaim manifesto — call all Han Chinese to arms\nDomestic: The Emperor leads the army in person — victory or death\nProduction: All craftsmen work day and night on siege engines",
                ],
            },
        },
        "qing": {
            1: {
                "zh": [
                    "[qing_t1_invade]【⚔️ 两路南征】\n军事：多铎出潼关取河南，阿济格出居庸关经山西取陕西\n外交：发布登极诏灭流寇安天下，号召前明官员归附\n内政：圈地安置八旗家眷于北京周边，整顿顺天府治安\n生产：征调蒙古马匹补充骑兵，在山西设马场",
                    "[qing_t1_persuade]【🤝 政治诱降】\n军事：暂缓大规模南征，先巩固已占领土\n外交：遣使至南京以吊崇祯讨闯贼为名试探南明\n内政：在占领州县维持原官制，不剃发不圈地以收民心\n生产：恢复华北漕运，以经济稳定换取政治支持",
                    "[qing_t1_consolidate]【🏰 巩固北方】\n军事：豪格镇守北京，济尔哈朗平定直隶地方叛乱\n外交：册封吴三桂为平西王，命关宁铁骑为南征先锋\n内政：在盛京推行汉法科举，吸收汉族士人入朝\n生产：恢复辽东屯田，减轻对关内粮食依赖",
                ],
                "en": [
                    "[qing_t1_invade]【⚔️ Two-Pronged Invasion】\nMilitary: Dodo through Tong Pass, Ajige through Juyong Pass\nDiplomacy: Ascension Edict — pacify the realm\nDomestic: Allot lands for Eight Banners families around Beijing\nProduction: Requisition Mongol horses, establish stud farms in Shanxi",
                    "[qing_t1_persuade]【🤝 Political Persuasion】\nMilitary: Pause invasion — consolidate occupied territories\nDiplomacy: Envoys to Nanjing under pretext of mourning Chongzhen\nDomestic: Keep Ming officials — no queue-cutting, no land seizure\nProduction: Restore North China canal transport for stability",
                    "[qing_t1_consolidate]【🏰 Consolidate the North】\nMilitary: Haoge holds Beijing, Jirgalang pacifies local rebels\nDiplomacy: Invest Wu Sangui as Prince Who Pacifies the West\nDomestic: Civil service exams in Shengjing, recruit Han scholars\nProduction: Restore military farms in Liaodong",
                ],
            },
            2: {
                "zh": [
                    "[qing_t2_storm]【⚡ 猛攻山东】\n军事：济尔哈朗率八旗主力攻山东，限期两月破济南\n外交：向占领州县发布剃发令，留头不留发震慑汉人\n内政：收编降清明军组建汉军八旗以汉制汉\n生产：在山东设立粮台征粮，以战养战",
                    "[qing_t2_recruit]【🤝 招降汉将】\n军事：维持前线压力但不强攻，围而不打\n外交：分别致书刘泽清刘良佐高杰黄得功，许以高官厚禄\n内政：优待已投降的汉官，树立榜样吸引更多人归附\n生产：在后方推行满汉分治，保护农业不误农时",
                    "[qing_t2_divide]【🔍 分兵略地】\n军事：主力攻山东，偏师取河南南阳切断明朝南北联系\n外交：遣使赴郑芝龙许以闽粤王试探其立场\n内政：在北京开科举吸引北方士人入朝\n生产：征调朝鲜火铳手补充火器部队",
                ],
                "en": [
                    "[qing_t2_storm]【⚡ Storm Shandong】\nMilitary: Jirgalang leads Eight Banner main force — Jinan in two months\nDiplomacy: Queue-cutting edict in occupied prefectures\nDomestic: Integrate surrendered Ming troops into Han Eight Banners\nProduction: Grain requisition stations in Shandong",
                    "[qing_t2_recruit]【🤝 Recruit Han Generals】\nMilitary: Maintain pressure but besiege rather than assault\nDiplomacy: Write to the four Ming generals — promise rank and riches\nDomestic: Treat surrendered Han officials as examples\nProduction: Manchu-Han dual governance — protect agriculture",
                    "[qing_t2_divide]【🔍 Divide and Conquer】\nMilitary: Main force takes Shandong, flanking force seizes Nanyang\nDiplomacy: Envoy to Zheng Zhilong — Prince of Fujian-Guangdong?\nDomestic: Civil service exams in Beijing for northern scholars\nProduction: Requisition Korean musketeers for firearms units",
                ],
            },
            3: {
                "zh": [
                    "[qing_t3_siege]【🔥 围攻扬州】\n军事：多铎率主力十五万兵临扬州，限期七日破城\n外交：多次致书史可法劝降，以高官厚禄瓦解南明核心\n内政：整编汉军八旗，提拔有功汉将\n生产：封锁京杭运河断绝南明漕运补给线",
                    "[qing_t3_demand]【🕊️ 招降南明】\n军事：重兵压境但不攻城，围城打援消耗南明兵力\n外交：遣使赴南京许以弘光帝仍居南京为王诱降\n内政：预先准备安民告示承诺官仍其职民复其业\n生产：在占领区推行减税政策，以经济优势吸引南明百姓",
                    "[qing_t3_amphibious]【🌊 水陆并进】\n军事：在瓜洲渡口集结战船准备渡江，骑兵沿江佯动\n外交：重金贿赂郑芝龙，以共享江南赋税换取郑氏中立\n内政：调蒙古骑兵至前线，八旗步兵休整待命\n生产：征用山东船匠赶造战船，朝鲜提供造船木材",
                ],
                "en": [
                    "[qing_t3_siege]【🔥 Siege of Yangzhou】\nMilitary: Dodo with 150,000 troops — seven days to breach\nDiplomacy: Repeated letters to Shi Kefa offering highest rank\nDomestic: Promote meritorious Han generals in Han Eight Banners\nProduction: Blockade the Grand Canal — cut off Ming grain supply",
                    "[qing_t3_demand]【🕊️ Demand Ming Surrender】\nMilitary: Besiege and bleed their reinforcements\nDiplomacy: Hongguang keeps Nanjing as a vassal king\nDomestic: Prepare pacification proclamations\nProduction: Tax reduction in occupied zones to attract Ming commoners",
                    "[qing_t3_amphibious]【🌊 Land and Sea】\nMilitary: Warships at Guazhou Ferry — cavalry feints along riverbank\nDiplomacy: Bribe Zheng Zhilong with shared Jiangnan tax revenue\nDomestic: Rotate Mongol cavalry to front, rest infantry\nProduction: Shandong shipwrights for warships, Korean timber",
                ],
            },
            4: {
                "zh": [
                    "[qing_t4_cross]【💥 渡江决战】\n军事：乘南明内讧之机全线渡江，三路直取南京\n外交：发布只诛首恶余者不究瓦解南明抵抗意志\n内政：北京留守豪格筹备登基大典\n生产：在扬州设大营粮仓，保障渡江大军补给",
                    "[qing_t4_amnesty]【📜 政治招安】\n军事：大军驻扎江北威慑，暂不渡江\n外交：遣使南京提出弘光帝封王保留江南半壁\n内政：在已占领区推行满汉通婚促进融合\n生产：恢复淮河以北农业生产，打造长期对峙的经济基础",
                    "[qing_t4_terror]【🏴 屠城立威】\n军事：破扬州后纵兵屠掠十日，震慑江南\n外交：将扬州屠城消息传遍江南各城\n内政：八旗将士论功行赏\n生产：掠夺扬州财富充作军饷，运粮北上",
                ],
                "en": [
                    "[qing_t4_cross]【💥 Cross the Yangtze】\nMilitary: Exploit Ming strife — three-pronged crossing for Nanjing\nDiplomacy: Only the ringleaders punished — break Ming will\nDomestic: Haoge in Beijing prepares coronation\nProduction: Main supply depot at Yangzhou for crossing army",
                    "[qing_t4_amnesty]【📜 Political Amnesty】\nMilitary: Mass forces on north bank as deterrence\nDiplomacy: Hongguang keeps his title, Ming keeps half of Jiangnan\nDomestic: Manchu-Han intermarriage for integration\nProduction: Restore agriculture north of Huai River",
                    "[qing_t4_terror]【🏴 Terrorize Jiangnan】\nMilitary: After Yangzhou, ten days of slaughter — shock Jiangnan\nDiplomacy: Spread news — surrender and live, resist and die\nDomestic: Eight Banner troops rewarded with treasure\nProduction: Loot Yangzhou's wealth for payroll",
                ],
            },
        },
        "nongminjun": {
            1: {
                "zh": [
                    "[nongmin_t1_hold]【🏰 死守襄阳】\n军事：集中全部兵力在襄阳构筑纵深防线\n外交：遣使至南明以共抗清军为名，争取粮饷援助\n内政：在襄阳推行均田免赋收拢流民\n生产：在四川广积粮草建立大后方",
                    "[nongmin_t1_strike]【⚔️ 北击清军】\n军事：趁清军主力南下，奇袭陕西牵制清军后路\n外交：联络张献忠旧部在四川整合兵力\n内政：没收襄阳官僚资产充作军饷\n生产：在汉中设立马场驯养战马",
                    "[nongmin_t1_allyming]【🤝 联明抗清】\n军事：与南明约定东西呼应，牵制清军侧翼\n外交：正式向南明称臣换取秦王封号和粮饷\n内政：停止追赃助饷政策安抚士绅\n生产：开放襄阳商路与南明互通贸易",
                ],
                "en": [
                    "[nongmin_t1_hold]【🏰 Hold Xiangyang】\nMilitary: Concentrate all forces in a deep defense\nDiplomacy: Envoy to Southern Ming for joint resistance and grain\nDomestic: Land reform and tax exemption to attract refugees\nProduction: Stockpile grain in Sichuan as secure rear base",
                    "[nongmin_t1_strike]【⚔️ Strike North】\nMilitary: Raid Shaanxi to threaten Qing's rear while they march south\nDiplomacy: Contact Zhang Xianzhong's remnants in Sichuan\nDomestic: Confiscate Xiangyang gentry assets for war\nProduction: Horse farms in Hanzhong to breed cavalry mounts",
                    "[nongmin_t1_allyming]【🤝 Ally with Ming】\nMilitary: Coordinate with Southern Ming for east-west pincer\nDiplomacy: Submit to Ming for Prince of Qin title and grain\nDomestic: End pursuit-and-confiscation policy to appease gentry\nProduction: Open Xiangyang trade routes with Southern Ming",
                ],
            },
            2: {
                "zh": [
                    "[nongmin_t2_recover]【🌾 休养生息】\n军事：固守现有城池不主动出击\n外交：与南明郑氏均保持非战关系\n内政：在四川推行屯田制恢复农业生产\n生产：开矿冶铁打造农具兵器",
                    "[nongmin_t2_wait]【⚔️ 伺机而动】\n军事：在清军与南明交战时，出兵占领河南南阳\n外交：与郑芝龙秘密结盟，约定事成后瓜分南明\n内政：收编流民组建新军\n生产：在襄阳设火药局自制火器",
                    "[nongmin_t2_warlord]【🔀 割据一方】\n军事：放弃襄阳退守四川，据险自守\n外交：分别向清和明称臣，左右逢源\n内政：在四川建立独立王国体制\n生产：开发蜀锦和井盐贸易积累财富",
                ],
                "en": [
                    "[nongmin_t2_recover]【🌾 Recover and Build】\nMilitary: Hold current cities, no offensive operations\nDiplomacy: Non-aggression with both Southern Ming and Zheng\nDomestic: Military farms in Sichuan to restore agriculture\nProduction: Open mines and smelters — tools and weapons",
                    "[nongmin_t2_wait]【⚔️ Wait and Strike】\nMilitary: Seize Nanyang when Qing and Ming are locked in battle\nDiplomacy: Secret pact with Zheng Zhilong — divide Ming after victory\nDomestic: Absorb refugees into new army units\nProduction: Gunpowder workshops in Xiangyang",
                    "[nongmin_t2_warlord]【🔀 Independent Warlord】\nMilitary: Abandon Xiangyang, retreat to Sichuan's defenses\nDiplomacy: Submit to both Qing and Ming — play both sides\nDomestic: Independent kingdom structure in Sichuan\nProduction: Shu brocade and salt well trade for wealth",
                ],
            },
            3: {
                "zh": [
                    "[nongmin_t3_hold]【🏰 坚守待变】\n军事：在襄阳和四川修筑双层防线持久抗战\n外交：观察各方战局，待清明两败俱伤后再出手\n内政：实行军屯制自给自足不扰民\n生产：在山丘地带广设堡垒和粮仓",
                    "[nongmin_t3_retake]【⚔️ 反攻关中】\n军事：趁清军主力缠斗于江南，突袭西安收复关中\n外交：号召前明西北边军旧部起义响应\n内政：宣布恢复汉家天下收拢关中民心\n生产：在关中平原推行屯田恢复粮食生产",
                    "[nongmin_t3_joinming]【📜 投靠南明】\n军事：全军东进与南明会师共守长江\n外交：李自成亲赴南京面见弘光帝以示诚意\n内政：解散大顺政权正式并入南明\n生产：将四川粮草运往江南支援前线",
                ],
                "en": [
                    "[nongmin_t3_hold]【🏰 Hold and Wait】\nMilitary: Double-layer defenses for protracted war\nDiplomacy: Observe — strike when Qing and Ming exhaust each other\nDomestic: Military self-sufficiency through farming\nProduction: Fortresses and granaries throughout the hills",
                    "[nongmin_t3_retake]【⚔️ Retake Guanzhong】\nMilitary: Raid Xi'an while Qing is entangled in Jiangnan\nDiplomacy: Call on former Ming frontier troops to rise up\nDomestic: Proclaim Restoration of Han rule to win hearts\nProduction: Restore farming on the Guanzhong plain",
                    "[nongmin_t3_joinming]【📜 Join Southern Ming】\nMilitary: All forces march east to join Ming on the Yangtze\nDiplomacy: Li Zicheng travels to Nanjing to meet Hongguang\nDomestic: Dissolve the Shun dynasty — integrate into Ming\nProduction: Ship Sichuan grain east to support the front",
                ],
            },
            4: {
                "zh": [
                    "[nongmin_t4_offensive]【⚔️ 大举北伐】\n军事：乘清军疲惫之机全线出击收复河南\n外交：以恢复汉室号召天下豪杰起兵\n内政：颁布明律恢复秩序\n生产：在收复区推行减税恢复生产",
                    "[nongmin_t4_retreat]【⛰️ 退守四川】\n军事：放弃襄阳全面退守四川盆地\n外交：向清朝称臣换取蜀王封号\n内政：在四川建立世袭割据政权\n生产：开发四川盐铁资源自给自足",
                    "[nongmin_t4_surrender]【🤝 投靠清朝】\n军事：全军解除武装接受清朝改编\n外交：李自成亲赴北京向多尔衮称臣\n内政：交出襄阳四川换取清朝保全民命\n生产：将积存粮草上缴清军换取优待",
                ],
                "en": [
                    "[nongmin_t4_offensive]【⚔️ Grand Northern Offensive】\nMilitary: Exploit Qing exhaustion — retake Henan\nDiplomacy: Call on all heroes to restore the Han\nDomestic: Promulgate Ming law to restore order\nProduction: Tax reduction in recovered territories",
                    "[nongmin_t4_retreat]【⛰️ Retreat to Sichuan】\nMilitary: Abandon Xiangyang, full retreat to Sichuan basin\nDiplomacy: Submit to Qing for Prince of Shu title\nDomestic: Hereditary warlord regime in Sichuan\nProduction: Develop Sichuan salt and iron for self-sufficiency",
                    "[nongmin_t4_surrender]【🤝 Surrender to Qing】\nMilitary: All troops disarm and accept reorganization\nDiplomacy: Li Zicheng kneels before Dorgon in Beijing\nDomestic: Hand over territories in exchange for sparing lives\nProduction: Surrender stored grain to Qing for preferential treatment",
                ],
            },
        },
        "zheng": {
            1: {
                "zh": [
                    "[zheng_t1_maritime]【🌊 海洋帝国】\n军事：扩编水师至三万人，控制台湾海峡至日本航线\n外交：与荷兰东印度公司谈判以生丝换火炮\n内政：在厦门泉州设立海关征收商税\n生产：在福建广东广设船厂大造远洋商船",
                    "[zheng_t1_serve]【🤝 勤王抗清】\n军事：派水师五千人溯长江至南京勤王\n外交：正式接受南明册封效忠弘光朝廷\n内政：以郑氏忠义号召闽粤士绅捐资助战\n生产：在福州设军器局为南明供应火器",
                    "[zheng_t1_watch]【⏳ 观望待变】\n军事：不派陆上部队参战，仅维持水师巡海\n外交：同时接受清和明的使节但不明确站队\n内政：保境安民不增税不征兵\n生产：大力发展海上贸易积累财富",
                ],
                "en": [
                    "[zheng_t1_maritime]【🌊 Maritime Empire】\nMilitary: Expand fleet to 30,000 — Taiwan Strait to Japan\nDiplomacy: Dutch East India Company — silk for cannons\nDomestic: Customs houses in Xiamen and Quanzhou\nProduction: Shipyards across Fujian and Guangdong",
                    "[zheng_t1_serve]【🤝 Serve the Ming】\nMilitary: 5,000 marines up the Yangtze to Nanjing\nDiplomacy: Accept Southern Ming investiture — pledge loyalty\nDomestic: Rally Fujian-Guangdong gentry under Zheng banner\nProduction: Armory in Fuzhou to supply Ming with firearms",
                    "[zheng_t1_watch]【⏳ Watch and Wait】\nMilitary: No land forces committed — naval patrols only\nDiplomacy: Receive envoys from both Qing and Ming\nDomestic: Peace and prosperity — no new taxes\nProduction: Maximize maritime trade to accumulate wealth",
                ],
            },
            2: {
                "zh": [
                    "[zheng_t2_trade]【💰 通商富国】\n军事：仅维持海岸防御不参与大陆战争\n外交：与日本签订朱印船贸易协定\n内政：免除闽粤渔税商税刺激贸易\n生产：引进吕宋白银铸造郑氏银元",
                    "[zheng_t2_buildup]【⚓ 扩军备战】\n军事：招募沿海渔民组建三万水师陆战队\n外交：向荷兰购买最新式火炮装备战船\n内政：在漳州设水师学堂培养海军将领\n生产：在泉州设大型军械所仿制红夷大炮",
                    "[zheng_t2_double]【🤝 两面外交】\n军事：表面勤王实则保存实力\n外交：同时遣使南京和北京，待价而沽\n内政：在福州修建坚固城防以备不测\n生产：囤积粮食军火应对未来变局",
                ],
                "en": [
                    "[zheng_t2_trade]【💰 Trade Empire】\nMilitary: Coastal defense only — no mainland wars\nDiplomacy: Red-seal trade agreements with Japan\nDomestic: Abolish fishing and commercial taxes\nProduction: Import Luzon silver for Zheng silver dollars",
                    "[zheng_t2_buildup]【⚓ Military Buildup】\nMilitary: Recruit 30,000 fishermen as marine corps\nDiplomacy: Purchase Dutch cannons to arm warships\nDomestic: Naval academy in Zhangzhou\nProduction: Major arsenal in Quanzhou — replicate cannons",
                    "[zheng_t2_double]【🤝 Double Game】\nMilitary: Publicly serve Ming, preserve strength\nDiplomacy: Envoys to both capitals — highest bidder wins\nDomestic: Fortify Fuzhou heavily\nProduction: Stockpile grain and ammunition",
                ],
            },
            3: {
                "zh": [
                    "[zheng_t3_march]【⚔️ 北上勤王】\n军事：郑芝龙亲率水师主力北上救援南京\n外交：要求弘光帝封郑氏世袭闽粤两省\n内政：动员闽粤全部资源支援前线\n生产：赶造登陆艇和浮桥装备渡江作战",
                    "[zheng_t3_defend]【🏰 守闽拒清】\n军事：在闽北山区设置防线阻止清军入闽\n外交：与清军谈判以不攻福建为条件保持中立\n内政：收容南明难民充实福建人口\n生产：在山口关隘修建堡垒群",
                    "[zheng_t3_diplomacy]【🌐 全面外交】\n军事：控制沿海岛屿为大本营分散风险\n外交：同时与清、明、荷兰、日本保持外交关系\n内政：将郑氏打造为各方都需要的中立贸易伙伴\n生产：建立从长崎到马六甲的贸易帝国",
                ],
                "en": [
                    "[zheng_t3_march]【⚔️ March North】\nMilitary: Zheng Zhilong leads main fleet to relieve Nanjing\nDiplomacy: Demand hereditary rule over Fujian and Guangdong\nDomestic: Mobilize all resources for war\nProduction: Rush-build landing craft and pontoon bridges",
                    "[zheng_t3_defend]【🏰 Defend Fujian】\nMilitary: Defensive lines in northern Fujian mountains\nDiplomacy: Neutrality in exchange for do-not-attack-Fujian\nDomestic: Absorb Southern Ming refugees\nProduction: Fortress complexes at every mountain pass",
                    "[zheng_t3_diplomacy]【🌐 Full Diplomacy】\nMilitary: Control offshore islands as safe havens\nDiplomacy: Relations with Qing, Ming, Dutch, Japan\nDomestic: Zheng clan as neutral trade partner\nProduction: Trade empire from Nagasaki to Malacca",
                ],
            },
            4: {
                "zh": [
                    "[zheng_t4_commit]【💪 全面参战】\n军事：出动全部水陆兵力参与南明最后的抗战\n外交：要求南明将台湾正式割让给郑氏\n内政：宣布郑成功为世子稳固继承\n生产：将全部海上贸易转为军火采购",
                    "[zheng_t4_taiwan]【🏝️ 固守台湾】\n军事：放弃闽粤大陆退守台湾澎湖\n外交：与荷兰结盟共抗清朝保护台湾\n内政：移民闽粤百姓至台湾充实人口\n生产：开发台湾农业实现粮食自给",
                    "[zheng_t4_submit]【📜 投靠清朝】\n军事：交出闽粤接受清军进驻\n外交：向多尔衮称臣换取靖海侯世袭\n内政：保留郑氏商团和海贸特权\n生产：将战船改造为商船继续海上贸易",
                ],
                "en": [
                    "[zheng_t4_commit]【💪 Full Commitment】\nMilitary: All naval and land forces for Ming's final stand\nDiplomacy: Demand formal cession of Taiwan to Zheng clan\nDomestic: Proclaim Zheng Chenggong as heir\nProduction: Convert maritime trade to arms procurement",
                    "[zheng_t4_taiwan]【🏝️ Hold Taiwan】\nMilitary: Abandon mainland — retreat to Taiwan and Penghu\nDiplomacy: Ally with Dutch against Qing to protect Taiwan\nDomestic: Migrate civilians to Taiwan\nProduction: Develop Taiwan agriculture for food self-sufficiency",
                    "[zheng_t4_submit]【📜 Submit to Qing】\nMilitary: Hand over Fujian-Guangdong to Qing garrison\nDiplomacy: Kneel to Dorgon for hereditary Marquis title\nDomestic: Retain Zheng merchant fleet and trade privileges\nProduction: Convert warships to merchant vessels",
                ],
            },
        },
    },
}

# ── Backward compat alias ──
FIRST_TURN_SUGGESTIONS = {
    k: v[1]["zh"]
    for k, v in EARLY_TURNS_SUGGESTIONS.get("three-kingdoms", {}).items()
}


def create_initial_world(player_faction_id: str, scenario: str = "three-kingdoms") -> WorldState:
    """Create a fresh world state for a new game (v1).

    Faction data is loaded from the scenario JSON (e.g. 207_liubei.json)
    rather than hardcoded Python dicts.

    This function is only designed for the Three Kingdoms scenario. Other
    scenarios are handled by ScenarioLoader in room_manager.py.
    """
    from ..engine.log_exporter import clear_session_log
    from .loader import load_scenario, load_territories

    clear_session_log()

    state = WorldState()
    state.scenario = scenario
    state.player_faction_id = player_faction_id

    scenario_data = load_scenario(scenario)
    factions_data = scenario_data.get("factions", {}) if scenario_data else {}

    for fid, fd in factions_data.items():
        state.factions[fid] = FactionState(
            id=fid,
            name=fd["name"],
            ruler_id=fd.get("ruler", ""),
            capital=fd.get("capital", ""),
            strength=fd.get("strength", 5000),
            economy=fd.get("economy", 50),
            morale=fd.get("morale_actual", 50),
            treasury=fd.get("treasury", 5000),
            food=fd.get("food", 3000),
            territories=list(fd.get("territories", [])),
        )

    # Load territories so build_faction_status_for_api can compute population
    import contextlib

    with contextlib.suppress(Exception):
        state.territories = load_territories(scenario)

    save_world(state)
    return state


# ─── V2 faction maps ──────────────────────────────────────────────
# (imported at top of file)


def _suppress_stderr():
    """Context manager to suppress stderr during optional LLM calls."""
    import sys as _sys

    class _Suppress:
        def __enter__(self):
            self._stderr = _sys.stderr
            _sys.stderr = open(os.devnull, "w")
            return self

        def __exit__(self, *args):
            _sys.stderr.close()
            _sys.stderr = self._stderr

    return _Suppress()


def _inject_v3_into_baseline(baseline_result, v3_delta: dict) -> None:
    """Inject v3 delta events into baseline for narrative generation."""
    if not hasattr(baseline_result, "character_events"):
        baseline_result.character_events = []
    if not hasattr(baseline_result, "diplomatic_events"):
        baseline_result.diplomatic_events = []

    # Add political events as character/diplomatic events
    for pe in v3_delta.get("political_events", []):
        baseline_result.character_events.append(
            {
                "event": pe.get("type", "court_dispute"),
                "description": pe.get("description", ""),
                "faction": pe.get("faction", ""),
            }
        )

    # Add npc actions as diplomatic events
    for na in v3_delta.get("npc_actions", []):
        baseline_result.diplomatic_events.append(
            {
                "faction": na.get("faction", ""),
                "action": na.get("action", ""),
                "target": na.get("target", ""),
                "reason": na.get("reasoning", ""),
            }
        )

    # Add morale events
    for me in v3_delta.get("morale_events", []):
        baseline_result.character_events.append(
            {
                "event": "morale_change",
                "faction": me.get("faction", ""),
                "change": me.get("change", 0),
                "reason": me.get("reason", ""),
            }
        )


def _auto_mobilize_for_attack(commands: list, world_state) -> None:
    """Auto-mobilize faction reserves for attack commands in v3 mode.

    When a player says "attack with 60K from wancheng" but only 5K army
    exists, transfer faction.strength_actual reserves to the army.
    """
    from histrategy_engine.world import UnitType

    faction = world_state.factions.get(world_state.player_faction_id)
    if not faction:
        return

    for cmd in commands:
        if getattr(cmd, "type", "") != "attack":
            continue
        source = cmd.params.get("source_territory", "")
        requested = cmd.params.get("amount", 0)
        if not source or not requested:
            continue

        army = None
        for a in world_state.armies.values():
            if a.location == source and a.faction_id == world_state.player_faction_id:
                army = a
                break
        if not army:
            continue

        current = army.total_troops
        reserves = faction.strength_actual - current
        needed = min(requested - current, reserves)

        if needed > 0 and needed <= reserves:
            infantry_needed = int(needed * 0.9)
            cavalry_needed = needed - infantry_needed
            army.units[UnitType.INFANTRY] = army.units.get(UnitType.INFANTRY, 0) + infantry_needed
            army.units[UnitType.CAVALRY] = army.units.get(UnitType.CAVALRY, 0) + cavalry_needed
            faction.strength_actual -= needed


def _build_faction_id_map(ws) -> dict[str, str]:
    """Build a lookup map from various name formats → faction pinyin ID.

    Handles LLM outputs that may use Chinese names (e.g. "曹操"),
    annotated names (e.g. "曹操(cao)"), or bare pinyin IDs.
    """
    id_map: dict[str, str] = {}
    for fid, f in ws.factions.items():
        id_map[fid] = fid  # "cao" → "cao"
        if hasattr(f, "name") and f.name:
            id_map[f.name] = fid  # "曹操" → "cao"
    return id_map


def _build_territory_id_map(ws) -> dict[str, str]:
    """Build a lookup map from various name formats → territory pinyin ID.

    Handles LLM outputs that may use Chinese names (e.g. "襄阳"),
    or bare pinyin IDs (e.g. "xiangyang").
    """
    id_map: dict[str, str] = {}
    for tid, t in ws.territories.items():
        id_map[tid] = tid  # "xiangyang" → "xiangyang"
        if hasattr(t, "name") and t.name:
            id_map[t.name] = tid  # "襄阳" → "xiangyang"
    return id_map


def apply_event_effects(world_state: V2WorldState, effects: dict) -> None:
    """Apply the outcomes/effects of a triggered historical event directly to WorldState."""
    from histrategy_engine.world import FactionState

    def transfer_territory(tid: str, fid: str):
        if tid in world_state.territories:
            old_owner_id = world_state.territories[tid].owner_id
            world_state.territories[tid].owner_id = fid
            # Remove from old owner's territories list
            if old_owner_id and old_owner_id in world_state.factions:
                old_faction = world_state.factions[old_owner_id]
                if tid in old_faction.territories:
                    old_faction.territories.remove(tid)
            # Add to new owner's territories list
            if fid and fid in world_state.factions:
                new_faction = world_state.factions[fid]
                if tid not in new_faction.territories:
                    new_faction.territories.append(tid)

    for key, value in effects.items():
        # 1. Advisor joining
        # e.g., "liubei_advisor": "zhugeliang"
        if key.endswith("_advisor") and value and value != "none":
            faction_id = key.split("_")[0]
            faction_id = V2_FACTION_MAP.get(faction_id, faction_id)
            char = world_state.characters.get(value)
            if char:
                char.faction_id = faction_id
                char.loyalty = 95
                char.alive = True
                ruler_id = world_state.factions.get(faction_id, FactionState()).ruler_id
                ruler = world_state.characters.get(ruler_id)
                if ruler:
                    char.location = ruler.location

        # 2. Characters dying/status changes
        # e.g., "guanyu_dead": True, "zhangfei_dead": True
        elif key.endswith("_dead") and value is True:
            char_id = key.rsplit("_", 1)[0]
            char = world_state.characters.get(char_id)
            if char:
                char.alive = False

        # 3. Locations
        # e.g., "liubei_location": "jiangkou"
        elif key.endswith("_location") and value:
            char_id = key.rsplit("_", 1)[0]
            char = world_state.characters.get(char_id)
            if char:
                char.location = value

        # 4. Territory ownership
        # e.g., "jingzhou_owner": "cao" or "liubei" or "sunquan"
        elif key == "jingzhou_owner" and value:
            target_fid = V2_FACTION_MAP.get(value, value)
            for tid in ["xiangyang", "jiangling", "jiangxia", "changsha", "lingling", "wuling", "guiyang", "nanyang"]:
                transfer_territory(tid, target_fid)

        # e.g. "liubei_controls": "yizhou"
        elif key.endswith("_controls") and value:
            target_fid = V2_FACTION_MAP.get(key.split("_")[0], key.split("_")[0])
            if value == "yizhou":
                for tid in ["chengdu", "hanshui", "hanzhong", "ziyang", "baqi"]:
                    transfer_territory(tid, target_fid)
            elif value == "jingzhou":
                for tid in [
                    "xiangyang",
                    "jiangling",
                    "jiangxia",
                    "changsha",
                    "lingling",
                    "wuling",
                    "guiyang",
                    "nanyang",
                ]:
                    transfer_territory(tid, target_fid)

        # e.g., "liubei_territories_add": ["wuling", "changsha", "lingling", "guiyang"]
        elif key.endswith("_territories_add") and isinstance(value, list):
            target_fid = V2_FACTION_MAP.get(key.split("_")[0], key.split("_")[0])
            for tid in value:
                transfer_territory(tid, target_fid)

        # 5. Relations
        # e.g., "sunliu_relation": "+20" or "-10"
        elif key.endswith("_relation") and value:
            f1_f2 = key.rsplit("_", 1)[0]
            f1, f2 = None, None
            if "sunliu" in f1_f2 or "sun_liu" in f1_f2:
                f1, f2 = "wu", "shu"
            if f1 and f2:
                try:
                    delta = int(value)
                    fac1 = world_state.factions.get(f1)
                    if fac1:
                        fac1.relations[f2] = max(-100, min(100, fac1.relations.get(f2, 0) + delta))
                    fac2 = world_state.factions.get(f2)
                    if fac2:
                        fac2.relations[f1] = max(-100, min(100, fac2.relations.get(f1, 0) + delta))
                except Exception:
                    pass

        # 6. Army/Power losses
        elif key.endswith("_army") and value == "devastated":
            fid = key.split("_")[0]
            fid = V2_FACTION_MAP.get(fid, fid)
            faction = world_state.factions.get(fid)
            if faction:
                faction.strength_actual = max(1000, int(faction.strength_actual * 0.3))
        elif key.endswith("_power") and value == "crippled":
            fid = key.split("_")[0]
            fid = V2_FACTION_MAP.get(fid, fid)
            faction = world_state.factions.get(fid)
            if faction:
                faction.strength_actual = max(1000, int(faction.strength_actual * 0.4))
                faction.treasury = max(500, int(faction.treasury * 0.5))
                faction.food = max(500, int(faction.food * 0.5))


# ═══════════════════════════════════════════════════════════════
# Historical footnotes — static lookup table for per-turn education
# ═══════════════════════════════════════════════════════════════

HISTORICAL_FOOTNOTES: dict[str, dict[int, dict[str, str]]] = {
    "nanming": {
        1: {
            "zh": "📜 史实：1645年夏，清军攻陷扬州，史可法殉国。多铎下令屠城十日，"
                 "江南震怖。弘光朝廷内斗不休，四镇各怀异心，无人救援扬州。",
            "en": "📜 History: Summer 1645, Qing forces sacked Yangzhou. Shi Kefa died a "
                 "martyr. Dodo ordered ten days of slaughter. The Hongguang court, "
                 "paralyzed by infighting, sent no reinforcements.",
        },
        2: {
            "zh": "📜 史实：1645年秋，清廷颁布剃发令——'留头不留发，留发不留头'。"
                 "江南士绅震怒，各地爆发抗清起义。李自成在湖北九宫山被地主武装杀死。",
            "en": "📜 History: Autumn 1645, the Qing issued the queue edict. Jiangnan gentry "
                 "rose in revolt. Li Zicheng was killed by local militia at Jiugong Mountain.",
        },
        3: {
            "zh": "📜 史实：1645年冬，清军主力南下，弘光帝出逃被俘。南京不战而降，"
                 "弘光朝廷覆灭。郑芝龙在福州拥立隆武帝，南明退守福建沿海。",
            "en": "📜 History: Winter 1645, Qing forces marched south. The Hongguang Emperor "
                 "fled and was captured. Nanjing surrendered without a fight. Zheng Zhilong "
                 "enthroned the Longwu Emperor in Fuzhou.",
        },
        4: {
            "zh": "📜 史实：1646年春，清军追击隆武朝廷至福建。郑芝龙暗中降清，"
                 "隆武帝被俘殉国。南明残余退往广东，绍武帝即位仅40天即覆灭。",
            "en": "📜 History: Spring 1646, Qing forces pursued the Longwu court into Fujian. "
                 "Zheng Zhilong secretly surrendered. The Longwu Emperor was captured. "
                 "Ming remnants fled to Guangdong — the Shaowu Emperor lasted only 40 days.",
        },
        5: {
            "zh": "📜 史实：1646年夏，张献忠在四川凤凰山战死。大西军余部由孙可望、"
                 "李定国率领南下云南。南明永历帝在广东肇庆即位，开始长达16年的西南抗清。",
            "en": "📜 History: Summer 1646, Zhang Xianzhong died in battle in Sichuan. His "
                 "remnant army marched south to Yunnan under Sun Kewang and Li Dingguo. "
                 "The Yongli Emperor was enthroned in Zhaoqing — 16 years of resistance began.",
        },
        6: {
            "zh": "📜 史实：1646年秋，清军攻入广东，绍武朝廷覆灭。永历帝逃往广西。"
                 "郑成功在金门起兵抗清，拒绝随父降清，成为南明最后的海上力量。",
            "en": "📜 History: Autumn 1646, Qing forces entered Guangdong. The Shaowu court "
                 "collapsed. Yongli fled to Guangxi. Zheng Chenggong (Koxinga) raised troops "
                 "at Jinmen, refusing to surrender with his father.",
        },
        7: {
            "zh": "📜 史实：1647年春，清军主力北撤休整。永历朝廷在广西、湖南一带"
                 "重整旗鼓，大西军余部与南明联手，一度收复湖南大片失地。",
            "en": "📜 History: Spring 1647, Qing main forces withdrew north to regroup. "
                 "The Yongli court reorganized in Guangxi and Hunan, joining forces with "
                 "Zhang Xianzhong's remnant army to retake much of Hunan.",
        },
        8: {
            "zh": "📜 史实：1647年夏，广东义军陈邦彦、张家玉、陈子壮起兵抗清"
                 "(广东三忠)。虽最终失败，但牵制了清军主力，为永历朝廷争取了时间。",
            "en": "📜 History: Summer 1647, the Three Loyalists of Guangdong rose against "
                 "the Qing. Though ultimately defeated, they tied down Qing forces, giving "
                 "the Yongli court precious time.",
        },
    },
}


def get_historical_footnote(scenario: str, turn: int, lang: str = "zh") -> str | None:
    """Get the historical footnote for a given scenario and turn.

    Returns None if no footnote exists for this scenario/turn combination.
    """
    scenario_data = HISTORICAL_FOOTNOTES.get(scenario, {})
    turn_data = scenario_data.get(turn, {})
    return turn_data.get(lang)
