import React from 'react';
import { Box, Typography, Paper, Fade, Avatar, Chip } from '@mui/material';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import PersonOutlineIcon from '@mui/icons-material/PersonOutline';
import RecordVoiceOverIcon from '@mui/icons-material/RecordVoiceOver';

const TypingAnimation = () => (
  <Box
    sx={{
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 0.7,
    }}
  >
    {[0, 1, 2].map((i) => (
      <Box
        key={i}
        sx={{
          width: 8,
          height: 8,
          backgroundColor: '#7dd3fc',
          borderRadius: 1,
          animation: 'pulse 1.4s infinite ease-in-out',
          animationDelay: `${i * 0.16}s`,
          opacity: 0.7,
          '@keyframes pulse': {
            '0%, 100%': {
              transform: 'translateY(0)',
              opacity: 0.45,
            },
            '50%': {
              transform: 'translateY(-8px)',
              opacity: 1,
            },
          },
        }}
      />
    ))}
  </Box>
);

const inferAssistantTag = (content = '') => {
  const lower = content.toLowerCase();
  if (lower.includes('手撕代码') || lower.includes('代码题') || lower.includes('贴出你的代码') || lower.includes('实现一个')) {
    return '代码题';
  }
  if (lower.includes('leetcode') || lower.includes('时间复杂度') || lower.includes('空间复杂度') || lower.includes('链表') || lower.includes('数组')) {
    return '代码追问';
  }
  if (lower.includes('八股') || lower.includes('http') || lower.includes('token') || lower.includes('幂等') || lower.includes('索引')) {
    return '基础追问';
  }
  if (lower.includes('follow-up') || lower.includes('why') || lower.includes('what would you')) {
    return '追问';
  }
  if (lower.includes('design') || lower.includes('architecture') || lower.includes('scal')) {
    return '方案设计';
  }
  if (lower.includes('experience') || lower.includes('situation') || lower.includes('challenge')) {
    return '经历深挖';
  }
  return '技术追问';
};

const MessageBubble = ({ content, role, isStreaming = false }) => {
  const isCandidate = role === 'user';
  const speaker = isCandidate ? '候选人' : 'AI 面试官';
  const tag = isCandidate ? '回答' : inferAssistantTag(content);

  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: isCandidate ? 'row-reverse' : 'row',
        alignItems: 'flex-start',
        mb: 2.5,
        gap: 1.5,
      }}
    >
      <Avatar
        sx={{
          width: 42,
          height: 42,
          flexShrink: 0,
          bgcolor: isCandidate ? 'rgba(245, 158, 11, 0.16)' : 'rgba(125, 211, 252, 0.16)',
          color: isCandidate ? '#fbbf24' : '#7dd3fc',
          border: '1px solid rgba(255,255,255,0.08)',
        }}
      >
        {isCandidate ? <PersonOutlineIcon /> : <RecordVoiceOverIcon />}
      </Avatar>

      <Paper
        elevation={0}
        sx={{
          px: 2.25,
          py: 1.75,
          maxWidth: '78%',
          borderRadius: 1,
          background: isCandidate
            ? 'linear-gradient(180deg, rgba(245,158,11,0.14) 0%, rgba(245,158,11,0.08) 100%)'
            : 'linear-gradient(180deg, rgba(14,165,233,0.14) 0%, rgba(15,23,42,0.92) 100%)',
          border: isCandidate
            ? '1px solid rgba(245,158,11,0.16)'
            : '1px solid rgba(125,211,252,0.16)',
          color: '#e5eef9',
          position: 'relative',
          minHeight: isStreaming && !content ? 88 : 'auto',
        }}
      >
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 1.5,
            mb: 1,
          }}
        >
          <Box>
            <Typography variant="subtitle2" sx={{ fontWeight: 700, color: '#f8fafc', lineHeight: 1.2 }}>
              {speaker}
            </Typography>
            <Typography variant="caption" sx={{ color: 'rgba(226,232,240,0.72)', lineHeight: 1.35 }}>
              {isCandidate ? '已记录你的作答内容' : '由 AI 面试官发起的问题'}
            </Typography>
          </Box>
          <Chip
            label={tag}
            size="small"
            sx={{
              flexShrink: 0,
              bgcolor: isCandidate ? 'rgba(245,158,11,0.16)' : 'rgba(125,211,252,0.14)',
              color: isCandidate ? '#fbbf24' : '#7dd3fc',
              border: '1px solid rgba(255,255,255,0.08)',
              fontWeight: 600,
            }}
          />
        </Box>

        {isCandidate ? (
          <Typography
            sx={{
              whiteSpace: 'pre-wrap',
              lineHeight: 1.75,
              fontSize: '0.98rem',
              color: '#e5eef9',
              wordBreak: 'keep-all',
              overflowWrap: 'break-word',
            }}
          >
            {content}
          </Typography>
        ) : (
          <>
            {isStreaming && !content ? (
              <Fade in timeout={800}>
                <Box
                  sx={{
                    minHeight: 72,
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'center',
                    alignItems: 'flex-start',
                    gap: 1.5,
                  }}
                >
                  <TypingAnimation />
                  <Typography variant="body2" sx={{ color: 'rgba(226,232,240,0.72)' }}>
                    面试官正在准备下一道问题...
                  </Typography>
                </Box>
              </Fade>
            ) : (
              <Box
                sx={{
                  color: '#e5eef9',
                  fontSize: '0.98rem',
                  lineHeight: 1.75,
                  '& p': {
                    m: 0,
                    mb: 1.2,
                    wordBreak: 'keep-all',
                    overflowWrap: 'break-word',
                  },
                  '& p:last-child': {
                    mb: 0,
                  },
                  '& span': {
                    wordBreak: 'keep-all',
                    overflowWrap: 'break-word',
                  },
                  '& ul, & ol': {
                    m: 0,
                    mb: 1.2,
                    pl: 2.5,
                  },
                  '& li': {
                    mb: 0.65,
                  },
                  '& li:last-child': {
                    mb: 0,
                  },
                  '& strong': {
                    color: '#f8fafc',
                    fontWeight: 700,
                  },
                  '& code': {
                    fontFamily: 'monospace',
                  },
                }}
              >
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  rehypePlugins={[rehypeHighlight]}
                  components={{
                    p: ({ node, ...props }) => <Box component="p" {...props} />,
                    pre: ({ node, ...props }) => (
                      <Box
                        component="pre"
                        sx={{
                          backgroundColor: 'rgba(15, 23, 42, 0.85)',
                          p: 1.5,
                          my: 1.2,
                          borderRadius: 1,
                          overflowX: 'auto',
                          border: '1px solid rgba(148,163,184,0.16)',
                          lineHeight: 1.6,
                        }}
                        {...props}
                      />
                    ),
                    code: ({ node, inline, ...props }) =>
                      inline ? (
                        <Box
                          component="code"
                          sx={{
                            backgroundColor: 'rgba(15, 23, 42, 0.85)',
                            px: 0.7,
                            py: 0.25,
                            borderRadius: 1,
                          }}
                          {...props}
                        />
                      ) : (
                        <Box
                          component="code"
                          sx={{
                            display: 'block',
                            whiteSpace: 'pre-wrap',
                          }}
                          {...props}
                        />
                      ),
                    ul: ({ node, ...props }) => <Box component="ul" {...props} />,
                    ol: ({ node, ...props }) => <Box component="ol" {...props} />,
                    li: ({ node, ...props }) => <Box component="li" {...props} />,
                  }}
                >
                  {content}
                </ReactMarkdown>
              </Box>
            )}
          </>
        )}
      </Paper>
    </Box>
  );
};

export default MessageBubble;
