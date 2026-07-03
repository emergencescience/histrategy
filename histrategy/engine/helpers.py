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
                    "【整肃朝纲】召集内阁廷议，命马士英与东林党和解，调史可法督师江北四镇",
                    "【布置江淮防线】命史可法赴扬州整编刘泽清、高杰、黄得功、刘良佐四镇兵马",
                    "【拉拢左良玉】遣使赴武昌以楚王爵位安抚左良玉，确保上江不叛",
                    "【安抚江南士绅】降低苏松常镇四府赋税，开江南恩科招揽士心",
                ],
                "en": [
                    "【Court Reform】Convene the Grand Council, order Ma Shiying to reconcile with the Donglin faction; dispatch Shi Kefa to Jiangbei",
                    "【Yangtze–Huai Defense】Send Shi Kefa to Yangzhou to reorganize the Four Garrisons of Jiangbei",
                    "【Secure Zuo Liangyu】Send envoys to Wuchang offering princely titles to keep Zuo Liangyu loyal",
                    "【Tax Relief】Lower taxes across Jiangnan prefectures and open civil service examinations to win scholar support",
                ],
            },
            2: {
                "zh": [
                    "【整顿漕运】疏通京杭大运河，确保江南粮饷北运供应前线",
                    "【整军经武】在南京设军器局打造火器，命各镇加紧操练",
                    "【联清拒闯？】内阁激烈辩论：联清剿闯还是联闯抗清，必须定策",
                    "【外交郑氏】遣使赴闽，以海防总兵官衔拉拢郑芝龙，合击清军水师",
                ],
                "en": [
                    "【Secure the Canal】Clear the Grand Canal to ensure Jiangnan grain reaches the front lines",
                    "【Arms Industry】Establish an armory in Nanjing; mass-produce firearms for the garrisons",
                    "【Grand Strategy Debate】The court is divided — ally with Qing against the peasant rebels, or ally with the rebels against Qing?",
                    "【Court the Zhengs】Dispatch envoys to Fujian offering Zheng Zhilong an admiralty to unite against Qing naval forces",
                ],
            },
            3: {
                "zh": [
                    "【扬州告急】清军多铎部兵临扬州城下，史可法血书求援，命各镇火速增援",
                    "【迁都之议】朝中分为两派：留守南京决战还是迁都杭州或福州以保存社稷",
                    "【调左良玉东下】以'清君侧'之名调左良玉大军沿江东下，实则避其与清军合流",
                    "【郑氏勤王】急诏郑芝龙率水师溯江而上，在长江口截击清军渡江船队",
                ],
                "en": [
                    "【Yangzhou Under Siege】Dodo's Qing forces surround Yangzhou; Shi Kefa writes in blood for reinforcements",
                    "【Relocate the Court?】The court splits — defend Nanjing to the death, or evacuate to Hangzhou or Fuzhou?",
                    "【Summon Zuo Liangyu】Call Zuo Liangyu's army eastward down the Yangtze under the pretext of 'purging corrupt ministers'",
                    "【Naval Reinforcement】Issue an urgent edict to Zheng Zhilong — sail up the Yangtze and intercept Qing crossing fleets",
                ],
            },
            4: {
                "zh": [
                    "【扬州十日】扬州城破，史可法殉国。清军屠城十日，江南震怖。必须决断",
                    "【南京保卫战】或御驾亲征激励士气，或君臣南逃避难——弘光朝的最后一搏",
                    "【求和与死战】多尔衮遣使劝降：称臣纳贡可保社稷。是降是战，三思而行",
                    "【联合农民军残部】李自成余部已退入湖南，遣使联络，共抗清军南下",
                ],
                "en": [
                    "【Fall of Yangzhou】The city falls; Shi Kefa dies a martyr. Qing forces massacre the city for ten days — all Jiangnan trembles",
                    "【Defend or Flee】Either the Hongguang Emperor leads the defense of Nanjing in person, or the court flees south — the dynasty's final gamble",
                    "【Surrender or Fight】Dorgon sends an envoy: submit as a vassal and the dynasty survives. Choose carefully",
                    "【Rebel Alliance】Li Zicheng's scattered forces have retreated into Hunan — send envoys to unite against the Qing advance",
                ],
            },
        },
        "qing": {
            1: {
                "zh": [
                    "【三路南征】命多铎出潼关攻河南，阿济格出居庸关经山西攻陕西，豪格镇守北京",
                    "【招降汉臣】发布《登极诏》宣称'灭流寇而安天下'，号召前明官员归附",
                    "【稳固京畿】圈地安置八旗将士家眷于北京周边，整顿顺天府治安收拢民心",
                    "【吴三桂封王】册封吴三桂为平西王，命其率关宁铁骑为南征先锋",
                ],
                "en": [
                    "【Three-Pronged Invasion】Order Dodo through Tong Pass into Henan, Ajige through Juyong Pass into Shaanxi, Haoge to hold Beijing",
                    "【Recruit Han Officials】Issue the Ascension Edict — 'Exterminate the rebels to pacify the realm'; call on former Ming officials to submit",
                    "【Secure the Capital】Allot lands around Beijing for the Eight Banners families; restore order in the metropolitan prefecture",
                    "【Ennoble Wu Sangui】Invest Wu Sangui as Prince Who Pacifies the West; order his elite Ningyuan cavalry to lead the southern campaign",
                ],
            },
            2: {
                "zh": [
                    "【攻取山东】命济尔哈朗率六万铁骑出直隶取山东，招降山东州县官吏",
                    "【西追闯贼】命阿济格吴三桂追击李自成残部入陕，绝其东山再起之机",
                    "【剃发令试行】在已占领州县颁布剃发令，'留头不留发，留发不留头'，震慑汉人",
                    "【试探江南】遣使赴南京以'吊崇祯帝、共讨闯贼'为名，试探南明朝廷虚实",
                ],
                "en": [
                    "【Conquer Shandong】Dispatch Jirgalang with 60,000 cavalry from Zhili into Shandong to subdue prefectural officials",
                    "【Hunt Li Zicheng】Order Ajige and Wu Sangui to pursue Li Zicheng's remnants into Shaanxi — crush them before they recover",
                    "【Queue Order】Issue the queue-cutting edict in occupied prefectures: 'Keep your hair, lose your head; keep your head, lose your hair'",
                    "【Probe Jiangnan】Send envoys to Nanjing under the pretext of 'mourning Chongzhen and hunting the rebels together' — test the Southern Ming",
                ],
            },
            3: {
                "zh": [
                    "【围攻扬州】多尔衮命多铎率主力十五万兵临扬州，限期七日破城",
                    "【招降史可法】多次遣使致书史可法劝降，以高官厚禄相诱，瓦解南明抵抗意志",
                    "【整编汉军八旗】收编降清的明军将领，组建汉军八旗，以汉制汉",
                    "【运河封锁】命水师封锁京杭运河，断绝南明漕运补给线",
                ],
                "en": [
                    "【Siege of Yangzhou】Dorgon orders Dodo with 150,000 troops to surround Yangzhou — the city must fall within seven days",
                    "【Demand Shi Kefa's Surrender】Send repeated letters to Shi Kefa offering high rank and riches — break the Ming resistance's spirit",
                    "【Form Han Banners】Integrate surrendered Ming generals into the Han Eight Banners — use Han to subdue Han",
                    "【Blockade the Canal】Order the navy to blockade the Grand Canal, cutting off Southern Ming's grain supply line",
                ],
            },
            4: {
                "zh": [
                    "【扬州屠城】城破后纵兵屠掠十日以震慑江南，'扬州十日'永载史册",
                    "【渡江作战】在瓜洲渡口集结战船，乘南明内讧之机强渡长江",
                    "【招抚江南】预先准备安民告示，承诺'官仍其职、民复其业'以减少抵抗",
                    "【南京受降】遣使赴南京诱降弘光朝臣，以'保全宗庙、不杀宗室'为条件",
                ],
                "en": [
                    "【Yangzhou Massacre】After breaching the walls, allow ten days of slaughter to terrorize Jiangnan into submission",
                    "【Cross the Yangtze】Assemble warships at Guazhou Ferry — exploit the Southern Ming's internal strife to force a crossing",
                    "【Pacify the South】Prepare proclamations promising officials keep their posts and civilians keep their land — minimize resistance",
                    "【Demand Nanjing's Surrender】Send envoys to Nanjing offering to spare the imperial temples and Ming princes — on condition of submission",
                ],
            },
        },
        "nongminjun": {
            1: {
                "zh": [
                    "【收编残部】李自成退至襄阳后收拢各地溃散义军，重整大顺政权旗号",
                    "【据守襄阳】加固襄阳城防，以汉水为屏障抵御清军南下和南明西进",
                    "【联明抗清试探】遣密使赴南京试探联合抗清——但南明视尔为'弑君之贼'，谈判极难",
                    "【分兵入蜀】命部将率偏师入川联络张献忠，建立川陕根据地互为犄角",
                ],
                "en": [
                    "【Rally the Scattered】Li Zicheng regroups broken units at Xiangyang; raise the Shun dynasty banner once more",
                    "【Hold Xiangyang】Fortify Xiangyang's walls, use the Han River as a barrier against both Qing and Southern Ming advances",
                    "【Probe Ming Alliance】Send secret envoys to Nanjing — but the Southern Ming sees you as the 'emperor-killer'; negotiations will be brutal",
                    "【Send Forces to Sichuan】Dispatch a detachment into Sichuan to link up with Zhang Xianzhong; establish a Shaanxi–Sichuan base",
                ],
            },
            2: {
                "zh": [
                    "【大西建国】张献忠在成都正式称帝建国号'大西'，改元大顺，与李自成互为呼应",
                    "【征粮养兵】在控制区实行'追赃助饷'，没收官绅田产充军，但小心激起民变",
                    "【防御清军西进】阿济格吴三桂已入陕，部署汉中防线阻止清军南下四川",
                    "【春耕屯田】在襄阳周边组织军屯，'高筑墙、广积粮'，准备长期对抗",
                ],
                "en": [
                    "【Great Western Kingdom】Zhang Xianzhong proclaims himself emperor in Chengdu — the 'Great Western' dynasty is born, echoing Li Zicheng",
                    "【Forced Requisitions】Seize gentry estates and granaries to feed the army, but peasant backlash could undo everything",
                    "【Block Qing's Western Push】Ajige and Wu Sangui have entered Shaanxi; deploy defenses at Hanzhong to stop Qing from entering Sichuan",
                    "【Garrison Farms】Organize military farms around Xiangyang — 'build high walls, stockpile grain' for the long war ahead",
                ],
            },
            3: {
                "zh": [
                    "【李过守襄阳】李自成已死，侄李过（李锦）继统大顺军，死守襄阳",
                    "【张献忠抗清】清军豪格部由陕西入川，张献忠率军迎击于川北",
                    "【转移根据地】若襄阳不守则西撤入川与张献忠合流，或南下湖南开辟新区",
                    "【联络南明残部】局势危急——何腾蛟在湖南拥立永历帝，或可暂时联手",
                ],
                "en": [
                    "【Li Guo Defends Xiangyang】Li Zicheng is dead; his nephew Li Guo commands the Shun army — hold Xiangyang at all costs",
                    "【Zhang Xianzhong Resists】Haoge's Qing forces enter Sichuan from Shaanxi; Zhang Xianzhong marches north to intercept",
                    "【Relocate the Base】If Xiangyang falls, retreat west into Sichuan to join Zhang Xianzhong, or push south into Hunan",
                    "【Contact Ming Remnants】Desperate times — He Tengjiao in Hunan has proclaimed the Yongli Emperor; a temporary alliance may be possible",
                ],
            },
            4: {
                "zh": [
                    "【川北血战】张献忠在凤凰山中箭身亡（或：成功伏击清军），大西军由李定国孙可望接管",
                    "【李过南下】襄阳失守，李过率余部沿汉水南下进入湖南，与何腾蛟联防",
                    "【联合抗清前线】李过与南明何腾蛟在湖南组成'十三镇'联军，开创农民军与明军合作先例",
                    "【入湘扎根】在湖南推行'均田免赋'政策，收拢流民充实兵力",
                ],
                "en": [
                    "【Bloody Northern Sichuan】Zhang Xianzhong falls to an arrow at Fenghuang Mountain — Li Dingguo and Sun Kewang take command of the Great Western Army",
                    "【Li Guo Retreats South】Xiangyang is lost; Li Guo leads remnants down the Han River into Hunan to join He Tengjiao's defense",
                    "【United Front】Li Guo and Ming loyalist He Tengjiao form the 'Thirteen Garrisons' coalition in Hunan — rebels and Ming forces fighting side by side",
                    "【Root in Hunan】Implement 'equal field, tax exempt' policies in Hunan; absorb refugees to swell the ranks",
                ],
            },
        },
        "zheng": {
            1: {
                "zh": [
                    "【扩建水师】在泉州、福州、厦门大造海船，招募沿海渔民入伍，打造东亚最强舰队",
                    "【控制海上贸易】垄断福建广东海上丝路贸易，征收'海商税'充实府库",
                    "【与南明结盟】遣使赴南京表示臣服弘光朝廷，换取'福建总兵'合法名分",
                    "【拒清拉拢】清廷密使来闽招降——拖延而不拒，观望天下大势",
                ],
                "en": [
                    "【Expand the Fleet】Build warships at Quanzhou, Fuzhou, and Xiamen; recruit coastal fishermen to forge East Asia's strongest navy",
                    "【Monopolize Maritime Trade】Seize control of the Fujian–Guangdong Silk Road sea lanes; impose merchant taxes to fill the treasury",
                    "【Pledge to the Ming】Send envoys to Nanjing swearing fealty to the Hongguang court in exchange for the official title 'Fujian Commander'",
                    "【Stall Qing Envoys】Qing secret emissaries arrive in Fujian with offers — stall without refusing; watch how the wind blows",
                ],
            },
            2: {
                "zh": [
                    "【经略台湾】遣水师进驻台湾大员（安平），设立屯垦据点作为家族退路",
                    "【与荷兰贸易】与盘踞台湾南部的荷兰东印度公司谈判，以生丝瓷器换取火器火炮",
                    "【勤王准备】清军南逼日急，命郑彩、郑联整合水师备战，随时准备北上勤王",
                    "【招揽士人】在福建开设'储贤馆'，招揽不愿降清的江南士大夫入幕",
                ],
                "en": [
                    "【Fortify Taiwan】Send the fleet to occupy Tayouan (Anping) in Taiwan; establish farming colonies as the family's fallback",
                    "【Trade with the Dutch】Negotiate with the Dutch East India Company in southern Taiwan — silk and porcelain for firearms and cannon",
                    "【Prepare to Save the Throne】Qing forces press south; order Zheng Cai and Zheng Lian to ready the fleet for a northern expedition",
                    "【Recruit Ming Scholars】Open a 'Talent Pavilion' in Fujian to attract Jiangnan scholar-officials who refuse to serve the Qing",
                ],
            },
            3: {
                "zh": [
                    "【北上勤王】郑芝龙亲率水师三千艘沿东海北上，进入长江口威慑清军",
                    "【控制长江口】在崇明岛、舟山群岛建立水寨，封锁清军渡江南下的海上通道",
                    "【隆武即位】唐王朱聿键逃至福建，郑芝龙在福州拥立其为隆武帝——挟天子以令诸侯",
                    "【南北通商】趁天下大乱维持福建中立通商地位，清、明双方的生意都要做",
                ],
                "en": [
                    "【Sail North】Zheng Zhilong personally leads 3,000 warships up the East China Sea to the Yangtze estuary, intimidating Qing forces",
                    "【Control the Estuary】Build naval forts on Chongming Island and the Zhoushan Archipelago; blockade Qing's sea route across the Yangtze",
                    "【Enthrone Longwu】The Tang Prince Zhu Yujian flees to Fujian; Zheng Zhilong crowns him the Longwu Emperor in Fuzhou — control the throne, command the realm",
                    "【Trade with Both Sides】In the chaos, maintain Fujian as a neutral trading hub — do business with Qing and Ming alike",
                ],
            },
            4: {
                "zh": [
                    "【隆武北伐筹备】隆武帝锐意北伐复兴明室，郑芝龙暗阻之——保存实力为上",
                    "【海上帝国】正式建立以福建为核心、北至日本南至马六甲的海上贸易帝国",
                    "【清廷招抚】清廷许以'闽粤王'之爵——降清则保富贵，但一旦剃发则失民心",
                    "【建设厦门基地】在厦门鼓浪屿修建水师大营和军械库，打造永不陷落的海上堡垒",
                ],
                "en": [
                    "【Longwu's Northern Crusade】The Longwu Emperor burns to retake the north; Zheng Zhilong quietly stalls — preserving strength comes first",
                    "【Maritime Empire】Formally build a sea-trade empire centered on Fujian, reaching from Japan in the north to Malacca in the south",
                    "【Qing's Offer】Qing offers the title 'Prince of Fujian and Guangdong' — submit and keep your wealth, but shaving your head means losing the people",
                    "【Fortify Xiamen】Build the naval headquarters and armory on Gulangyu Island opposite Xiamen — an unconquerable fortress at sea",
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
