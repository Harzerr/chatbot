import React, { useMemo } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Paper,
  Stack,
  Typography,
} from '@mui/material';

const DIMENSIONS = [
  { key: 'technical_accuracy', label: '技术准确性', color: '#7dd3fc' },
  { key: 'knowledge_depth', label: '知识深度', color: '#fbbf24' },
  { key: 'communication_clarity', label: '表达清晰度', color: '#34d399' },
  { key: 'logical_structure', label: '逻辑结构', color: '#c084fc' },
  { key: 'problem_solving', label: '问题解决', color: '#f472b6' },
  { key: 'job_match_score', label: '岗位匹配', color: '#2dd4bf' },
];

const RECOMMENDATION_MAP = {
  technical_accuracy: '回答前做一次技术事实校验，重点检查术语、机制与边界条件。',
  knowledge_depth: '每次回答增加“原理 + 取舍 + 场景”三段式，拉高深度分。',
  communication_clarity: '先给结论，再分点展开，最后补充案例，提升表达效率。',
  logical_structure: '强制使用 STAR 或 PREP 结构，避免叙述跳跃。',
  problem_solving: '显式展示“问题拆解 -> 方案对比 -> 决策依据”的过程。',
  job_match_score: '把回答主动对齐目标岗位职责，并补充可量化结果。',
};

const clampScore = (value) => {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 0;
  return Math.max(0, Math.min(100, Math.round(numeric)));
};

const average = (numbers) => {
  if (!numbers.length) return 0;
  return numbers.reduce((sum, value) => sum + value, 0) / numbers.length;
};

const averageBy = (items, key) => average(items.map((item) => Number(item?.[key] || 0)));

const stddev = (numbers) => {
  if (numbers.length < 2) return 0;
  const avg = average(numbers);
  const variance = average(numbers.map((value) => (value - avg) ** 2));
  return Math.sqrt(variance);
};

const parseTimestamp = (value) => {
  const timestamp = new Date(value || '').getTime();
  return Number.isNaN(timestamp) ? 0 : timestamp;
};

const formatShortDate = (timestamp) => {
  if (!timestamp) return '--';
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
  }).format(new Date(timestamp));
};

const formatSigned = (value, digits = 1) => {
  const numeric = Number(value || 0);
  const fixed = numeric.toFixed(digits);
  return numeric > 0 ? `+${fixed}` : fixed;
};

const buildReport = (messages = []) => {
  const sessionMap = new Map();

  messages.forEach((message) => {
    const chatId = String(message?.chat_id || '').trim();
    if (!chatId) return;

    if (!sessionMap.has(chatId)) {
      sessionMap.set(chatId, {
        chatId,
        latestTimestamp: 0,
        evaluations: [],
      });
    }

    const session = sessionMap.get(chatId);
    const timestamp = parseTimestamp(message?.timestamp);
    if (timestamp > session.latestTimestamp) {
      session.latestTimestamp = timestamp;
    }

    const evaluation = message?.evaluation;
    if (!evaluation || typeof evaluation !== 'object') return;

    const normalized = {
      overall: clampScore(evaluation.overall_score),
    };
    DIMENSIONS.forEach(({ key }) => {
      normalized[key] = clampScore(evaluation[key]);
    });
    session.evaluations.push(normalized);
  });

  const allSessions = Array.from(sessionMap.values()).sort((a, b) => a.latestTimestamp - b.latestTimestamp);
  const scoredSessions = allSessions
    .filter((session) => session.evaluations.length > 0)
    .map((session) => {
      const dimensionScores = {};
      DIMENSIONS.forEach(({ key }) => {
        dimensionScores[key] = Math.round(averageBy(session.evaluations, key));
      });

      return {
        ...session,
        ...dimensionScores,
        overall: Math.round(averageBy(session.evaluations, 'overall')),
      };
    });

  if (!scoredSessions.length) {
    return {
      hasData: false,
      totalSessions: allSessions.length,
      scoredSessions: 0,
      totalAnswers: 0,
      latestOverall: null,
      improvement: 0,
      stability: 0,
      trendPoints: [],
      radar: DIMENSIONS.map((dimension) => ({
        ...dimension,
        latest: 0,
        recent: 0,
      })),
      strengths: [],
      weaknesses: [],
      recommendations: [],
    };
  }

  const latestSession = scoredSessions[scoredSessions.length - 1];
  const recentFive = scoredSessions.slice(-5);
  const firstWindowSize = Math.min(3, scoredSessions.length);
  const firstWindow = scoredSessions.slice(0, firstWindowSize);
  const lastWindow = scoredSessions.slice(-firstWindowSize);

  const radar = DIMENSIONS.map((dimension) => ({
    ...dimension,
    latest: latestSession[dimension.key],
    recent: Math.round(averageBy(recentFive, dimension.key)),
  }));

  const weaknessRanking = [...radar].sort((a, b) => a.recent - b.recent);
  const strengthRanking = [...radar].sort((a, b) => b.recent - a.recent);

  return {
    hasData: true,
    totalSessions: allSessions.length,
    scoredSessions: scoredSessions.length,
    totalAnswers: scoredSessions.reduce((sum, session) => sum + session.evaluations.length, 0),
    latestOverall: latestSession.overall,
    improvement: averageBy(lastWindow, 'overall') - averageBy(firstWindow, 'overall'),
    stability: stddev(recentFive.map((session) => session.overall)),
    trendPoints: scoredSessions.slice(-10).map((session, index) => ({
      index: index + 1,
      dateLabel: formatShortDate(session.latestTimestamp),
      score: session.overall,
    })),
    radar,
    strengths: strengthRanking.slice(0, 2).map((item) => `${item.label}（${item.recent}）`),
    weaknesses: weaknessRanking.slice(0, 2).map((item) => `${item.label}（${item.recent}）`),
    recommendations: weaknessRanking
      .slice(0, 2)
      .map((item) => RECOMMENDATION_MAP[item.key] || '针对薄弱维度做专项练习。'),
  };
};

const GrowthLineChart = ({ points = [] }) => {
  if (!points.length) {
    return (
      <Typography variant="body2" sx={{ color: '#94a3b8' }}>
        暂无曲线数据
      </Typography>
    );
  }

  const width = 680;
  const height = 260;
  const margin = { top: 18, right: 20, bottom: 42, left: 40 };
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;

  const getX = (index) => (
    points.length === 1
      ? margin.left + (innerWidth / 2)
      : margin.left + ((index * innerWidth) / (points.length - 1))
  );
  const getY = (score) => margin.top + (((100 - clampScore(score)) * innerHeight) / 100);

  const path = points
    .map((point, index) => `${index === 0 ? 'M' : 'L'} ${getX(index)} ${getY(point.score)}`)
    .join(' ');

  const yTicks = [0, 20, 40, 60, 80, 100];

  return (
    <Box sx={{ width: '100%', overflowX: 'auto' }}>
      <Box
        component="svg"
        viewBox={`0 0 ${width} ${height}`}
        sx={{ width: '100%', minWidth: 560, display: 'block' }}
      >
        {yTicks.map((tick) => (
          <g key={tick}>
            <line
              x1={margin.left}
              y1={getY(tick)}
              x2={width - margin.right}
              y2={getY(tick)}
              stroke="rgba(148,163,184,0.18)"
              strokeWidth="1"
            />
            <text
              x={margin.left - 8}
              y={getY(tick) + 4}
              textAnchor="end"
              fill="#94a3b8"
              fontSize="11"
            >
              {tick}
            </text>
          </g>
        ))}

        <path d={path} fill="none" stroke="#38bdf8" strokeWidth="3" strokeLinecap="round" />

        {points.map((point, index) => (
          <g key={`${point.dateLabel}-${point.index}`}>
            <circle cx={getX(index)} cy={getY(point.score)} r="4.5" fill="#38bdf8" />
            <text
              x={getX(index)}
              y={height - 18}
              textAnchor="middle"
              fill="#94a3b8"
              fontSize="11"
            >
              {point.dateLabel}
            </text>
            <title>{`${point.dateLabel}: ${point.score}`}</title>
          </g>
        ))}
      </Box>
    </Box>
  );
};

const RadarChart = ({ data = [] }) => {
  if (!data.length) {
    return null;
  }

  const width = 440;
  const height = 330;
  const cx = 220;
  const cy = 160;
  const radius = 110;
  const levels = [20, 40, 60, 80, 100];
  const total = data.length;

  const angleAt = (index) => (-Math.PI / 2) + ((index * 2 * Math.PI) / total);
  const pointAt = (value, index, extend = 1) => {
    const safe = clampScore(value);
    const distance = radius * (safe / 100) * extend;
    const angle = angleAt(index);
    return {
      x: cx + (distance * Math.cos(angle)),
      y: cy + (distance * Math.sin(angle)),
    };
  };

  const polygonPoints = (field) => data
    .map((item, index) => {
      const point = pointAt(item[field], index);
      return `${point.x},${point.y}`;
    })
    .join(' ');

  return (
    <Box sx={{ width: '100%', overflowX: 'auto' }}>
      <Box
        component="svg"
        viewBox={`0 0 ${width} ${height}`}
        sx={{ width: '100%', minWidth: 360, display: 'block' }}
      >
        {levels.map((level) => (
          <polygon
            key={level}
            points={data.map((_, index) => {
              const point = pointAt(level, index);
              return `${point.x},${point.y}`;
            }).join(' ')}
            fill="none"
            stroke="rgba(148,163,184,0.22)"
            strokeWidth="1"
          />
        ))}

        {data.map((item, index) => {
          const axisEnd = pointAt(100, index);
          const labelPoint = pointAt(100, index, 1.16);
          return (
            <g key={item.key}>
              <line
                x1={cx}
                y1={cy}
                x2={axisEnd.x}
                y2={axisEnd.y}
                stroke="rgba(148,163,184,0.26)"
                strokeWidth="1"
              />
              <text
                x={labelPoint.x}
                y={labelPoint.y}
                textAnchor="middle"
                dominantBaseline="middle"
                fill="#cbd5e1"
                fontSize="11"
              >
                {item.label}
              </text>
            </g>
          );
        })}

        <polygon
          points={polygonPoints('recent')}
          fill="rgba(125,211,252,0.20)"
          stroke="#7dd3fc"
          strokeWidth="2"
        />
        <polygon
          points={polygonPoints('latest')}
          fill="rgba(245,158,11,0.16)"
          stroke="#fbbf24"
          strokeWidth="2"
        />

        <g transform="translate(22, 312)">
          <rect x="0" y="-9" width="12" height="12" fill="rgba(125,211,252,0.20)" stroke="#7dd3fc" />
          <text x="18" y="1" fill="#cbd5e1" fontSize="12">近 5 场均值</text>
          <rect x="112" y="-9" width="12" height="12" fill="rgba(245,158,11,0.16)" stroke="#fbbf24" />
          <text x="130" y="1" fill="#cbd5e1" fontSize="12">最近 1 场</text>
        </g>
      </Box>
    </Box>
  );
};

const ProfileGrowthReport = ({
  messages = [],
  loading = false,
  error = '',
  onRetry = null,
}) => {
  const report = useMemo(() => buildReport(messages), [messages]);

  const metricCards = [
    { label: '总面试场次', value: report.totalSessions },
    { label: '有效评分场次', value: report.scoredSessions },
    { label: '累计作答轮次', value: report.totalAnswers },
    { label: '当前综合分', value: report.latestOverall ?? '--' },
    {
      label: '成长幅度',
      value: formatSigned(report.improvement),
      tone: report.improvement >= 0 ? '#34d399' : '#f87171',
    },
    {
      label: '稳定性(近5场σ)',
      value: Number(report.stability || 0).toFixed(1),
      tone: '#cbd5e1',
    },
  ];

  return (
    <Paper elevation={0} sx={{ p: 3, borderRadius: 3 }}>
      <Stack spacing={2}>
        <Box>
          <Typography variant="h6" sx={{ fontWeight: 700 }}>
            面试成长分析
          </Typography>
          <Typography variant="body2" sx={{ color: '#94a3b8', mt: 0.8 }}>
            基于历史面试评分生成成长曲线、能力分布与改进建议。
          </Typography>
        </Box>

        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress size={28} />
          </Box>
        ) : null}

        {!loading && error ? (
          <Alert
            severity="warning"
            action={onRetry ? <Button color="inherit" size="small" onClick={onRetry}>重试</Button> : null}
          >
            {error}
          </Alert>
        ) : null}

        {!loading && !error && !report.hasData ? (
          <Alert severity="info">
            暂无可分析的评分数据。完成至少一场有效面试后，会自动生成成长报告。
          </Alert>
        ) : null}

        {!loading && !error && report.hasData ? (
          <Stack spacing={2.4}>
            <Stack direction="row" spacing={1.1} useFlexGap flexWrap="wrap">
              {metricCards.map((card) => (
                <Chip
                  key={card.label}
                  label={`${card.label}：${card.value}`}
                  sx={{
                    bgcolor: 'rgba(148,163,184,0.12)',
                    color: card.tone || '#e2e8f0',
                    border: '1px solid rgba(148,163,184,0.20)',
                  }}
                />
              ))}
            </Stack>

            <Stack direction={{ xs: 'column', xl: 'row' }} spacing={2}>
              <Paper
                elevation={0}
                sx={{
                  p: 2,
                  borderRadius: 2,
                  flex: 1.18,
                  bgcolor: 'rgba(15,23,42,0.5)',
                  border: '1px solid rgba(125,211,252,0.14)',
                }}
              >
                <Typography variant="subtitle1" sx={{ mb: 0.6, fontWeight: 600 }}>
                  综合分成长曲线（近 10 场）
                </Typography>
                <Typography variant="caption" sx={{ color: '#94a3b8', display: 'block', mb: 0.8 }}>
                  趋势越平滑，说明发挥越稳定。
                </Typography>
                <GrowthLineChart points={report.trendPoints} />
              </Paper>

              <Paper
                elevation={0}
                sx={{
                  p: 2,
                  borderRadius: 2,
                  flex: 1,
                  bgcolor: 'rgba(15,23,42,0.5)',
                  border: '1px solid rgba(125,211,252,0.14)',
                }}
              >
                <Typography variant="subtitle1" sx={{ mb: 0.6, fontWeight: 600 }}>
                  能力分布雷达图
                </Typography>
                <Typography variant="caption" sx={{ color: '#94a3b8', display: 'block', mb: 2 ,mt:0.2}}>
                  对比“最近 1 场”与“近 5 场均值”。
                </Typography>
                <RadarChart data={report.radar} />
              </Paper>
            </Stack>

            <Paper
              elevation={0}
              sx={{
                p: 2,
                borderRadius: 2,
                bgcolor: 'rgba(15,23,42,0.5)',
                border: '1px solid rgba(125,211,252,0.14)',
              }}
            >
              <Stack spacing={1.2}>
                <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                  分析结论
                </Typography>
                <Typography variant="body2" sx={{ color: '#e2e8f0' }}>
                  优势维度：{report.strengths.join('、') || '暂无'}
                </Typography>
                <Typography variant="body2" sx={{ color: '#e2e8f0' }}>
                  待提升维度：{report.weaknesses.join('、') || '暂无'}
                </Typography>
                {report.recommendations.map((item) => (
                  <Typography key={item} variant="body2" sx={{ color: '#94a3b8', lineHeight: 1.7 }}>
                    • {item}
                  </Typography>
                ))}
              </Stack>
            </Paper>
          </Stack>
        ) : null}
      </Stack>
    </Paper>
  );
};

export default ProfileGrowthReport;
