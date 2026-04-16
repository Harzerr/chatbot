import re
from typing import Dict, List


ROLE_ALIASES: Dict[str, str] = {
    "前端工程师": "Web前端工程师",
    "web前端": "Web前端工程师",
    "web前端工程师": "Web前端工程师",
    "frontend engineer": "Web前端工程师",
    "后端工程师": "Java后端工程师",
    "java后端": "Java后端工程师",
    "java后端工程师": "Java后端工程师",
    "backend engineer": "Java后端工程师",
    "c++开发": "C++开发工程师",
    "c++开发工程师": "C++开发工程师",
    "c++工程师": "C++开发工程师",
    "cpp developer": "C++开发工程师",
    "测试": "测试工程师",
    "测试工程师": "测试工程师",
    "qa engineer": "测试工程师",
    "python算法": "Python算法工程师",
    "python算法工程师": "Python算法工程师",
    "算法工程师": "Python算法工程师",
    "algorithm engineer": "Python算法工程师",
}


ROLE_BANKS: Dict[str, Dict[str, object]] = {
    "Java后端工程师": {
        "definition": "面向 Java 技术栈的服务端研发岗位，重点考察后端基础、分布式系统、数据库、缓存、消息队列、线上稳定性与工程判断。",
        "core_stack": [
            "Java 基础、集合、多线程、JVM",
            "Spring Boot / Spring Cloud",
            "MySQL、Redis、消息队列",
            "微服务、接口设计、服务治理",
            "监控告警、日志排查、性能优化",
        ],
        "question_bank": {
            "技术面": [
                "Java 并发基础：线程池参数设计、锁升级、CAS、AQS、并发容器使用边界",
                "JVM：内存结构、垃圾回收器选择、线上 Full GC 排查、性能调优思路",
                "Spring：IOC/AOP 原理、事务传播、循环依赖、自动装配机制",
                "MySQL：索引设计、联合索引命中、事务隔离级别、慢查询优化、主从一致性",
                "Redis：缓存穿透/击穿/雪崩、防止脏读、热点 key、分布式锁边界",
                "MQ：消息可靠性、重复消费、顺序消费、幂等设计与重试补偿",
            ],
            "项目面": [
                "围绕候选人做过的后端项目深挖：业务目标、服务边界、核心接口、数据流转、性能瓶颈",
                "追问一个核心模块的方案选型：为什么这样设计、替代方案是什么、最终 trade-off 是什么",
                "追问线上故障：现象、止损、定位路径、根因、复盘与后续治理",
                "追问性能优化：基线指标、压测结果、优化动作、收益量化与副作用",
            ],
            "场景题": [
                "设计一个高并发秒杀/下单接口，如何处理库存一致性、限流、幂等和热点",
                "某接口 P99 延迟突然飙升，如何一步步定位是数据库、缓存、线程池还是下游依赖问题",
                "一个订单系统要拆分微服务，如何设计服务边界、事务一致性与可观测性",
            ],
            "行为面": [
                "推动接口规范、稳定性治理或重构落地时，如何说服团队并控制风险",
                "面对业务 deadline 和技术债冲突时，如何做取舍与沟通",
                "与产品、前端、测试协作处理线上事故的经历和反思",
            ],
            "系统设计": [
                "高并发评论/订单/支付系统设计",
                "缓存 + 数据库一致性方案设计",
                "消息驱动异步架构与失败补偿设计",
            ],
            "手撕代码": [
                "手写线程安全 LRU Cache 或延迟任务调度器",
                "手写一个支持重试与超时控制的 RPC/HTTP 调用包装器",
                "手写二叉树层序遍历、TopK、滑动窗口限流等常见题",
            ],
        },
        "knowledge_docs": [
            {
                "title": "Java后端核心技术栈",
                "tags": ["java", "spring", "mysql", "redis", "mq", "backend"],
                "content": (
                    "岗位核心技术栈包括 Java 基础、集合、多线程、JVM、Spring Boot、MySQL、Redis、消息队列、"
                    "微服务治理与可观测性。回答时要尽量结合真实业务链路说明技术使用场景，而不是只背定义。"
                ),
            },
            {
                "title": "Java后端常见面试考点",
                "tags": ["jvm", "事务", "索引", "缓存", "幂等", "分布式"],
                "content": (
                    "高频考点包括 JVM 调优、线程池参数、数据库索引与事务、缓存一致性、分布式锁、消息可靠性、"
                    "接口幂等、限流降级、线上故障排查。优秀候选人会讲出边界条件、失败场景和工程取舍。"
                ),
            },
            {
                "title": "Java后端优秀回答范例",
                "tags": ["回答模板", "项目深挖", "场景题", "示例"],
                "content": (
                    "示例：在秒杀接口优化里，我负责库存扣减链路设计。初版瓶颈在数据库行锁竞争，"
                    "后来改成 Redis 预扣 + MQ 异步落库 + 幂等校验，P99 从 480ms 降到 120ms。"
                    "同时增加限流、降级和补偿任务，复盘时重点修正了热点 key 和消息重复消费问题。"
                ),
            },
        ],
    },
    "C++开发工程师": {
        "definition": "面向 C++ 研发的系统/客户端/基础设施岗位，重点考察语言基础、内存模型、并发、多线程、网络、操作系统与工程性能优化。",
        "core_stack": [
            "C++11/14/17 语言特性、STL、模板",
            "对象模型、内存管理、智能指针、RAII",
            "多线程并发、锁、原子操作、线程池",
            "Linux、网络编程、系统调用、性能分析",
            "构建调试、崩溃排查、工程质量",
        ],
        "question_bank": {
            "技术面": [
                "C++ 对象模型、虚函数表、拷贝控制、移动语义、右值引用、完美转发",
                "智能指针、资源管理、内存泄漏、悬垂指针、RAII 设计思想",
                "多线程并发：mutex、condition_variable、atomic、内存序、死锁定位",
                "STL 常用容器底层结构、迭代器失效、复杂度与使用边界",
                "Linux 网络编程：socket、epoll、多路复用、零拷贝、粘包拆包",
                "性能优化与调试：gdb、perf、valgrind、asan、崩溃 dump 分析",
            ],
            "项目面": [
                "围绕候选人真实模块深挖：架构分层、线程模型、内存管理、性能瓶颈、崩溃问题",
                "追问一个核心性能优化案例：瓶颈定位、火焰图/指标分析、优化前后收益",
                "追问稳定性问题：崩溃复现、竞态排查、日志和 dump 分析路径",
            ],
            "场景题": [
                "设计一个高性能网络服务，如何处理连接管理、线程模型、内存池与背压",
                "线上偶发崩溃但难以复现，如何建立诊断链路并定位根因",
                "一个高频模块 CPU 占用异常，如何用工具和代码分析定位瓶颈",
            ],
            "行为面": [
                "如何推动底层组件重构或性能治理在团队中落地",
                "如何在交付压力下平衡性能优化与功能开发",
                "如何与测试或上层业务协作定位底层疑难问题",
            ],
            "手撕代码": [
                "手写线程安全队列、对象池或简化版 shared_ptr",
                "手写 LRU Cache、环形缓冲区或 epoll 事件分发核心逻辑",
                "手写二叉树、字符串处理、并发控制相关经典题",
            ],
        },
        "knowledge_docs": [
            {
                "title": "C++开发核心技术栈",
                "tags": ["c++", "stl", "linux", "network", "concurrency"],
                "content": "岗位核心技术栈包括现代 C++、STL、内存管理、多线程并发、Linux 系统、网络编程、调试和性能优化。回答时要体现语言机制和工程落地。",
            },
            {
                "title": "C++开发常见面试考点",
                "tags": ["移动语义", "虚函数", "智能指针", "epoll", "竞态", "调试"],
                "content": "高频考点包括对象生命周期、拷贝与移动、模板、虚函数、智能指针、锁与原子操作、epoll、内存泄漏、崩溃排查与性能优化。",
            },
            {
                "title": "C++开发优秀回答范例",
                "tags": ["回答模板", "性能优化", "示例"],
                "content": "示例：在行情处理模块里，我负责从单线程同步处理改造成多线程流水线，先用 perf 找到热点在序列化和锁竞争，再通过对象池、无锁队列和批量发送把吞吐提升了 2.3 倍，同时补充了线程退出和异常回收机制避免资源泄漏。",
            },
        ],
    },
    "测试工程师": {
        "definition": "面向测试/测开岗位，重点考察测试设计、质量保障、接口与自动化、缺陷定位、稳定性与工程化能力。",
        "core_stack": [
            "测试理论、测试设计方法、缺陷管理",
            "接口测试、自动化测试、持续集成",
            "抓包、日志分析、数据库校验",
            "性能测试、稳定性测试、质量度量",
            "测试平台、脚本开发与协作流程",
        ],
        "question_bank": {
            "技术面": [
                "测试用例设计：等价类、边界值、状态迁移、因果图在真实业务中的应用",
                "接口测试：鉴权、幂等、超时重试、数据构造、断言设计和脏数据清理",
                "自动化测试：分层设计、Mock、数据隔离、CI 门禁、误报治理",
                "缺陷定位：抓包、日志、数据库、环境差异、上下游依赖排查",
                "性能与稳定性：压测模型、瓶颈归因、容量评估、指标监控",
            ],
            "项目面": [
                "围绕真实测试项目深挖：业务链路、风险拆解、测试策略、上线问题与复盘",
                "追问一个高风险需求如何制定测试范围、优先级和上线门禁",
                "追问一次线上缺陷定位过程：复现、证据链、根因、回归与改进",
            ],
            "场景题": [
                "一个支付链路频繁超时，如何设计排查路径和回归验证方案",
                "需求频繁变化且时间紧，如何重新排序测试优先级并控制质量风险",
                "为 AI 对话/流式接口设计测试方案，如何覆盖状态流转和异常恢复",
            ],
            "行为面": [
                "如何推动开发接受质量门禁或缺陷治理机制",
                "如何在发布压力下坚持关键风险不过线",
                "如何和产品、开发处理需求不清或验收标准变化",
            ],
        },
        "knowledge_docs": [
            {
                "title": "测试岗位核心技术栈",
                "tags": ["qa", "接口测试", "自动化", "性能", "稳定性"],
                "content": "岗位核心技术栈包括测试设计、接口测试、自动化框架、日志与数据库排查、性能与稳定性测试、质量平台与协作机制。回答时要体现风险意识和质量取舍。",
            },
            {
                "title": "测试岗位常见面试考点",
                "tags": ["边界值", "幂等", "mock", "缺陷定位", "压测", "门禁"],
                "content": "高频考点包括边界值与状态迁移、接口幂等、自动化分层、Mock、缺陷定位、发布门禁、压测与稳定性分析。优秀候选人会给出具体证据链和回归策略。",
            },
            {
                "title": "测试岗位优秀回答范例",
                "tags": ["回答模板", "缺陷定位", "示例"],
                "content": "示例：在订单退款需求上线前，我把风险拆成鉴权、金额计算、重复提交、回调重试和账务一致性五块，优先覆盖主链路和历史缺陷热点。上线后发现偶发重复退款，我通过日志 traceId 和数据库流水比对定位到重试幂等失效，随后补充回归用例和发布门禁。",
            },
        ],
    },
    "Web前端工程师": {
        "definition": "面向 Web 应用研发的前端岗位，重点考察浏览器原理、JavaScript/TypeScript、框架设计、性能优化、工程化与线上质量。",
        "core_stack": [
            "HTML / CSS / JavaScript / TypeScript",
            "React 或 Vue 生态、状态管理、组件设计",
            "浏览器渲染机制、网络与缓存",
            "前端工程化、构建、测试、CI/CD",
            "监控埋点、性能优化、线上排障",
        ],
        "question_bank": {
            "技术面": [
                "浏览器输入 URL 到页面渲染的全过程，重点解释关键渲染路径与性能瓶颈",
                "JavaScript 原型链、闭包、事件循环、Promise、微任务宏任务与异步调度",
                "React / Vue 核心机制：组件更新、状态管理、diff、Hooks/组合式 API 设计",
                "TypeScript 类型系统：泛型、类型收窄、联合类型、工程中的约束价值",
                "前端性能优化：首屏、长列表、懒加载、缓存、代码分割、图片资源策略",
                "前端工程化：构建工具、模块化、测试、lint、发布回滚、灰度验证",
            ],
            "项目面": [
                "围绕候选人做过的前端项目深挖：页面复杂度、核心交互、状态流转、性能瓶颈、线上问题",
                "追问组件封装或页面架构：为什么这样拆、可复用性如何、如何避免状态失控",
                "追问一次线上故障：错误监控、复现路径、根因定位、修复与回归验证",
                "追问性能优化：指标基线、定位方法、优化手段、收益数据和副作用",
            ],
            "场景题": [
                "设计一个复杂后台管理系统前端架构，如何处理权限、路由、组件复用与状态管理",
                "某页面首屏慢且白屏率高，如何利用监控、埋点和性能分析工具定位问题",
                "一个富交互页面频繁卡顿，如何拆解是渲染、请求、计算还是资源加载问题",
            ],
            "行为面": [
                "如何推动前端规范、组件库或工程优化在团队中落地",
                "如何与产品和设计协作处理高频变更需求",
                "如何在赶上线和保证质量之间做取舍",
            ],
            "系统设计": [
                "大型前端应用架构设计",
                "组件库/低代码平台设计",
                "前端监控与埋点体系设计",
            ],
            "手撕代码": [
                "手写防抖、节流、深拷贝、Promise.all、发布订阅",
                "实现一个简化版状态管理或组件通信机制",
                "实现长列表虚拟滚动或缓存策略核心逻辑",
            ],
        },
        "knowledge_docs": [
            {
                "title": "Web前端核心技术栈",
                "tags": ["javascript", "typescript", "react", "vue", "browser", "frontend"],
                "content": (
                    "岗位核心技术栈包括 HTML、CSS、JavaScript、TypeScript、React/Vue、浏览器原理、性能优化、"
                    "工程化与线上监控。回答不能只停留在 API 使用，要体现原理理解和复杂页面落地经验。"
                ),
            },
            {
                "title": "Web前端常见面试考点",
                "tags": ["事件循环", "渲染", "hooks", "性能", "工程化", "监控"],
                "content": (
                    "高频考点包括事件循环、闭包、原型链、浏览器渲染、网络缓存、框架更新机制、"
                    "状态管理、性能优化、埋点监控、构建流程与线上排障。优秀回答要讲出具体指标和实战取舍。"
                ),
            },
            {
                "title": "Web前端优秀回答范例",
                "tags": ["回答模板", "项目深挖", "性能优化", "示例"],
                "content": (
                    "示例：在数据看板重构里，我负责页面拆分和性能治理。首版首屏时间 4.2s，"
                    "通过路由级代码分割、图表懒加载、接口并发控制和 memo 化渲染，把首屏降到 1.8s。"
                    "同时接入埋点和错误监控，定位到一次白屏由动态配置异常引起，并补上降级兜底。"
                ),
            },
        ],
    },
    "Python算法工程师": {
        "definition": "面向 Python 与算法建模方向的岗位，重点考察编程基础、算法与数据结构、机器学习/深度学习原理、实验设计与工程落地。",
        "core_stack": [
            "Python 基础、数据结构与工程规范",
            "机器学习/深度学习基础",
            "模型训练、评估指标、误差分析",
            "数据处理、特征工程、实验设计",
            "模型部署与推理优化",
        ],
        "question_bank": {
            "技术面": [
                "Python 数据结构、生成器、装饰器、多进程多线程、GIL 理解",
                "机器学习基础：偏差方差、过拟合、正则化、交叉验证、评价指标",
                "深度学习基础：反向传播、优化器、归一化、过拟合处理、模型调参",
                "数据处理与特征工程：缺失值、异常值、类别不平衡、特征选择",
                "模型部署：推理延迟、吞吐、显存占用、在线服务稳定性",
            ],
            "项目面": [
                "围绕真实算法项目深挖：任务目标、数据来源、标签质量、模型选型、实验设计、线上效果",
                "追问误差分析与 bad case 处理：哪些样本失败、如何定位、如何改进",
                "追问从离线指标到线上指标的差异和原因",
            ],
            "场景题": [
                "某分类模型离线 AUC 很高但线上效果差，如何系统排查",
                "训练数据严重不平衡，如何设计采样、损失函数和评估方案",
                "模型效果提升有限时，如何判断该继续调模型还是回头做数据治理",
            ],
            "行为面": [
                "如何与产品、标注、后端协作推进模型上线",
                "如何在实验资源有限的情况下安排优先级",
                "如何向非算法同学解释模型能力与边界",
            ],
        },
        "knowledge_docs": [
            {
                "title": "Python算法核心技术栈",
                "tags": ["python", "ml", "dl", "feature", "deployment"],
                "content": (
                    "岗位核心技术栈包括 Python 编程、机器学习与深度学习基础、数据处理、实验设计、"
                    "误差分析、模型部署与效果评估。回答时要兼顾理论、实验方法和工程落地。"
                ),
            },
            {
                "title": "Python算法优秀回答范例",
                "tags": ["回答模板", "实验设计", "误差分析", "示例"],
                "content": (
                    "示例：在缺陷检测项目里，我先分析数据分布发现正负样本极不均衡，于是采用 focal loss + 重采样，"
                    "并通过消融实验验证数据增强和 backbone 替换的收益。最终离线 F1 提升 6 个点，"
                    "上线后又根据 bad case 发现小目标漏检，继续补充了高分辨率切图和阈值校准。"
                ),
            },
        ],
    },
}


REAL_INTERVIEW_STYLES: Dict[str, List[str]] = {
    "Java后端工程师": [
        "追问必须落到真实业务链路、服务边界、数据一致性和线上稳定性。",
        "如果候选人只会背概念，要立刻追问实现细节、故障案例和技术取舍。",
    ],
    "Web前端工程师": [
        "追问必须落到真实页面复杂度、状态流转、性能指标和线上问题定位。",
        "如果候选人只会背 API，要立刻追问浏览器原理、框架机制和工程落地。",
    ],
    "Python算法工程师": [
        "追问必须落到数据集特征、实验设计、指标解释、bad case 和部署约束。",
        "如果候选人只会说模型名，要继续追问原理、调参依据和误差分析。",
    ],
    "C++开发工程师": [
        "追问必须落到对象生命周期、线程模型、系统调用、性能指标和崩溃定位。",
        "如果候选人只会背语言特性，要继续追问工程场景、工具链和线上问题处理。",
    ],
    "测试工程师": [
        "追问必须落到风险拆解、用例设计、缺陷证据链、回归策略和质量门禁。",
        "如果候选人只会背测试理论，要继续追问真实项目和上线事故复盘。",
    ],
}


ROUND_TYPE_ALIASES: Dict[str, str] = {
    "一面": "一面",
    "二面": "二面",
    "三面": "三面",
    "hr面": "HR面",
    "hr": "HR面",
    "hr round": "HR面",
    "项目面": "一面",
    "技术面": "一面",
    "八股面": "一面",
    "手撕代码": "二面",
    "算法面": "二面",
    "系统设计": "二面",
    "综合面": "三面",
    "行为面": "HR面",
    "hr round interview": "HR面",
}


ROUND_CATEGORY_PRIORITIES: Dict[str, List[str]] = {
    "一面": ["技术面", "项目面", "场景题"],
    "二面": ["项目面", "场景题", "系统设计", "手撕代码", "技术面"],
    "三面": ["项目面", "场景题", "行为面", "系统设计", "技术面"],
    "HR面": ["行为面", "项目面", "场景题"],
}


ROUND_GUIDANCE: Dict[str, str] = {
    "一面": "更像首轮技术筛选，优先核验基础是否扎实、项目是否真实做过、表达是否清楚。",
    "二面": "更像深入技术轮，优先深挖项目决策、复杂场景、系统设计或编码实现能力。",
    "三面": "更像综合终面，优先考察技术判断、复杂问题拆解、跨团队协作和成长潜力。",
    "HR面": "更像人事终轮，优先考察动机匹配、稳定性、沟通协作、价值观和职业规划。",
}


INTERVIEW_QUESTION_LIMITS = {
    "一面": 10,
    "二面": 10,
    "三面": 10,
    "HR面": 10,
}


RESOURCE_LIBRARY: Dict[str, List[dict]] = {
    "technical_accuracy": [
        {"title": "高频面试知识点专项训练", "category": "技术知识", "reason": "提升回答准确性与基础概念稳定性"},
        {"title": "经典项目复盘模板", "category": "实战总结", "reason": "用真实项目经验支撑技术回答"},
    ],
    "knowledge_depth": [
        {"title": "系统性原理学习清单", "category": "技术知识", "reason": "补强回答深度与原理层理解"},
        {"title": "架构与设计权衡案例", "category": "案例分析", "reason": "提升原理与工程实践的连接能力"},
    ],
    "communication_clarity": [
        {"title": "结构化表达练习法", "category": "沟通技巧", "reason": "提升回答清晰度和表达流畅度"},
        {"title": "1分钟观点表达训练", "category": "表达训练", "reason": "减少冗长和模糊表述"},
    ],
    "logical_structure": [
        {"title": "STAR 与 PREP 回答框架", "category": "沟通技巧", "reason": "帮助答案更有层次和逻辑"},
        {"title": "复杂问题拆解练习", "category": "思维训练", "reason": "增强问题分析与结构化能力"},
    ],
    "problem_solving": [
        {"title": "工程取舍与问题定位题库", "category": "面试题", "reason": "提升排障与权衡能力"},
        {"title": "场景化追问题训练", "category": "面试题", "reason": "提高面对深入追问时的应对能力"},
    ],
    "job_match_score": [
        {"title": "JD 关键词与项目证据对齐清单", "category": "岗位匹配", "reason": "把回答落到目标岗位真正关心的能力和成果"},
        {"title": "目标公司面试风格复盘表", "category": "岗位匹配", "reason": "让表达更贴合公司与岗位的考察偏好"},
    ],
}


COMPANY_INTERVIEW_STYLES: Dict[str, List[str]] = {
    "字节": [
        "强调算法、项目 impact、细节追问和快速反应。",
        "问题会直接、节奏快，喜欢追问复杂度、指标和最终价值。",
    ],
    "字节跳动": [
        "强调算法、项目 impact、细节追问和快速反应。",
        "问题会直接、节奏快，喜欢追问复杂度、指标和最终价值。",
    ],
    "阿里": [
        "强调业务理解、技术判断、协作能力和为什么这么做。",
        "偏好围绕系统稳定性、业务价值和跨团队推动来深挖。",
    ],
    "阿里巴巴": [
        "强调业务理解、技术判断、协作能力和为什么这么做。",
        "偏好围绕系统稳定性、业务价值和跨团队推动来深挖。",
    ],
    "腾讯": [
        "强调底层原理、扎实基础和刨根问底式追问。",
        "会追协议、源码机制、系统边界和设计合理性。",
    ],
    "美团": [
        "强调业务落地、工程效率、稳定性和执行力。",
        "问题偏务实，注重结果、效率和复盘。",
    ],
    "百度": [
        "强调技术基础、系统原理和工程实现。",
        "AI/搜索/数据相关岗位更关注原理深度和数学/模型理解。",
    ],
}


def normalize_interview_role(interview_role: str | None) -> str:
    role = (interview_role or "").strip()
    if not role:
        return "通用软件工程师"

    lowered = role.lower()
    if role in ROLE_BANKS:
        return role
    if lowered in ROLE_ALIASES:
        return ROLE_ALIASES[lowered]
    return ROLE_ALIASES.get(role, role)


def normalize_interview_round(interview_type: str | None) -> str:
    interview_kind = (interview_type or "").strip()
    if not interview_kind:
        return "一面"

    lowered = interview_kind.lower()
    if interview_kind in ROUND_CATEGORY_PRIORITIES:
        return interview_kind
    if lowered in ROUND_TYPE_ALIASES:
        return ROUND_TYPE_ALIASES[lowered]
    return ROUND_TYPE_ALIASES.get(interview_kind, "一面")


def _tokenize(text: str) -> set[str]:
    english_tokens = re.findall(r"[A-Za-z][A-Za-z0-9.+#_-]*", text.lower())
    chinese_tokens = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    return set(english_tokens + chinese_tokens)


def _retrieve_role_knowledge_docs(
    interview_role: str | None,
    interview_type: str | None,
    question: str | None = None,
    jd_content: str | None = None,
    resume_content: str | None = None,
    top_k: int = 3,
) -> List[dict]:
    role = normalize_interview_role(interview_role)
    role_bank = ROLE_BANKS.get(role)
    if not role_bank:
        return []

    query_text = " ".join(
        part for part in [role, interview_type or "", question or "", jd_content or "", resume_content or ""] if part
    )
    query_tokens = _tokenize(query_text)
    ranked: List[tuple[int, dict]] = []

    for doc in role_bank.get("knowledge_docs", []):
        doc_text = " ".join([doc["title"], " ".join(doc.get("tags", [])), doc["content"]])
        doc_tokens = _tokenize(doc_text)
        overlap = len(query_tokens & doc_tokens)
        score = overlap * 3
        if interview_type and interview_type in doc_text:
            score += 2
        if score == 0:
            score = 1
        ranked.append((score, doc))

    ranked.sort(key=lambda item: (-item[0], item[1]["title"]))
    return [doc for _, doc in ranked[:top_k]]


def get_question_bank_context(interview_role: str | None, interview_type: str | None) -> str:
    role = normalize_interview_role(interview_role)
    interview_round = normalize_interview_round(interview_type)
    role_bank = ROLE_BANKS.get(role)

    if not role_bank:
        return f"""
            ROLE-SPECIFIC COMPETENCY GUIDANCE:
            - 当前岗位未命中预设岗位化题库，请基于岗位名称、JD 和简历动态推断考察重点
            - 优先覆盖技术知识、项目深挖、场景题和行为题，不要只问单一类型问题
            """

    question_bank = role_bank["question_bank"]
    category_priorities = ROUND_CATEGORY_PRIORITIES.get(interview_round, ROUND_CATEGORY_PRIORITIES["一面"])
    selected_topics: List[str] = []
    selected_categories: List[str] = []

    for category in category_priorities:
        topics = question_bank.get(category) or []
        if not topics:
            continue
        selected_categories.append(category)
        selected_topics.extend(topics[:3])

    if not selected_topics:
        fallback_categories = ["技术面", "项目面", "场景题", "行为面"]
        for category in fallback_categories:
            topics = question_bank.get(category) or []
            if not topics:
                continue
            selected_categories.append(category)
            selected_topics.extend(topics[:2])

    core_stack = "\n".join([f"- {item}" for item in role_bank.get("core_stack", [])])
    topics = "\n".join([f"- {topic}" for topic in selected_topics])
    style_lines = REAL_INTERVIEW_STYLES.get(role, [])
    styles = "\n".join([f"- {item}" for item in style_lines]) if style_lines else "- 保持真实技术面试强度，持续深挖。"
    covered_categories = "、".join(question_bank.keys())
    current_round_categories = "、".join(selected_categories) if selected_categories else "技术面、项目面"
    round_guidance = ROUND_GUIDANCE.get(interview_round, ROUND_GUIDANCE["一面"])

    return f"""
            ROLE DEFINITION:
            - 标准岗位：{role}
            - 岗位说明：{role_bank["definition"]}
            - 已建设题库类别：{covered_categories}
            - 当前面试轮次：{interview_round}
            - 当前轮次重点：{round_guidance}
            - 当前轮次优先题库类别：{current_round_categories}

            ROLE CORE STACK:
            {core_stack}

            QUESTION BANK FOCUS FOR CURRENT ROUND:
            {topics}

            REAL INTERVIEW STYLE:
            {styles}

            QUESTION GENERATION CONSTRAINTS:
            - 上述内容是岗位化题库方向，不是固定题目原文
            - 题目必须结合当前轮次、候选人简历、JD 和上一轮回答动态生成
            - 当前题型之外，也要保持对技术知识、项目深挖、场景题、行为题的整体覆盖意识
            """


def get_role_knowledge_context(
    interview_role: str | None,
    interview_type: str | None,
    question: str | None = None,
    jd_content: str | None = None,
    resume_content: str | None = None,
) -> str:
    role = normalize_interview_role(interview_role)
    role_bank = ROLE_BANKS.get(role)
    if not role_bank:
        return ""

    docs = _retrieve_role_knowledge_docs(
        interview_role=role,
        interview_type=interview_type,
        question=question,
        jd_content=jd_content,
        resume_content=resume_content,
    )
    if not docs:
        return ""

    doc_blocks = []
    for doc in docs:
        tags = ", ".join(doc.get("tags", []))
        doc_blocks.append(
            f"- 文档标题：{doc['title']}\n"
            f"  标签：{tags}\n"
            f"  内容摘要：{doc['content']}"
        )

    return "ROLE KNOWLEDGE BASE RETRIEVAL:\n" + "\n".join(doc_blocks)


def build_role_knowledge_seed_documents() -> List[dict]:
    seed_documents: List[dict] = []

    for role, role_bank in ROLE_BANKS.items():
        seed_documents.append(
            {
                "role": role,
                "doc_type": "role_overview",
                "title": f"{role}岗位定义与核心技术栈",
                "tags": ["岗位定义", "核心技术栈"],
                "content": (
                    f"岗位：{role}\n"
                    f"岗位定义：{role_bank['definition']}\n"
                    f"核心技术栈：{'；'.join(role_bank.get('core_stack', []))}"
                ),
            }
        )

        for category, topics in role_bank.get("question_bank", {}).items():
            seed_documents.append(
                {
                    "role": role,
                    "doc_type": "question_bank",
                    "title": f"{role}{category}题库",
                    "tags": [category, "题库", "面试考点"],
                    "content": f"{category}重点：{'；'.join(topics)}",
                }
            )

        for knowledge_doc in role_bank.get("knowledge_docs", []):
            seed_documents.append(
                {
                    "role": role,
                    "doc_type": "knowledge_doc",
                    "title": knowledge_doc["title"],
                    "tags": knowledge_doc.get("tags", []),
                    "content": knowledge_doc["content"],
                }
            )

    return seed_documents


def get_interview_question_limit(interview_type: str | None) -> int:
    interview_round = normalize_interview_round(interview_type)
    return INTERVIEW_QUESTION_LIMITS.get(interview_round, 10)


def build_company_jd_resume_context(
    target_company: str | None,
    jd_content: str | None,
    resume_content: str | None,
) -> str:
    company = (target_company or "").strip()
    style_guidance = COMPANY_INTERVIEW_STYLES.get(company, [])
    style_text = "\n".join([f"- {item}" for item in style_guidance]) if style_guidance else "- 根据目标公司名称、岗位特征和 JD 内容推断面试风格。"

    jd_excerpt = (jd_content or "").strip()
    resume_excerpt = (resume_content or "").strip()

    return f"""
            COMPANY / JD / RESUME CONTEXT:
            - Target Company: {company or "未提供"}

            COMPANY STYLE GUIDANCE:
            {style_text}

            JD PARSING INSTRUCTIONS:
            - Extract core responsibilities, must-have skills, bonus skills, business context, and hidden expectations from the JD
            - Use JD keywords to decide what to ask first and what to dig deeper on
            - If JD is missing, infer common expectations from the selected role

            RESUME PARSING INSTRUCTIONS:
            - Extract the candidate's key projects, technical stack, strongest experiences, and likely weak spots
            - At least some project-round questions should feel anchored to the candidate's actual background rather than generic role questions
            - If the resume content is missing, use a reasonable ideal-candidate baseline instead of fabricating details

            JD CONTENT:
            {jd_excerpt[:3000] if jd_excerpt else "未提供 JD"}

            RESUME CONTENT:
            {resume_excerpt[:3000] if resume_excerpt else "未提供简历摘要"}
            """


def get_recommended_resources(low_dimensions: List[str]) -> List[dict]:
    resources: List[dict] = []
    seen_titles = set()

    for dimension in low_dimensions:
        for resource in RESOURCE_LIBRARY.get(dimension, []):
            if resource["title"] in seen_titles:
                continue
            resources.append(resource)
            seen_titles.add(resource["title"])

    return resources[:6]
