import React, { useEffect, useMemo, useState } from 'react';
import Editor from '@monaco-editor/react';
import {
  Box,
  TextField,
  IconButton,
  Typography,
  Tabs,
  Tab,
  MenuItem,
  Chip,
  Stack,
  Button,
  Dialog,
  DialogContent,
  Paper,
  Divider,
} from '@mui/material';
import SendRoundedIcon from '@mui/icons-material/SendRounded';
import CodeRoundedIcon from '@mui/icons-material/CodeRounded';
import ChatBubbleOutlineRoundedIcon from '@mui/icons-material/ChatBubbleOutlineRounded';
import DeleteOutlineRoundedIcon from '@mui/icons-material/DeleteOutlineRounded';
import PostAddRoundedIcon from '@mui/icons-material/PostAddRounded';
import OpenInFullRoundedIcon from '@mui/icons-material/OpenInFullRounded';
import CloseFullscreenRoundedIcon from '@mui/icons-material/CloseFullscreenRounded';
import PlayArrowRoundedIcon from '@mui/icons-material/PlayArrowRounded';

const languageOptions = [
  { value: 'cpp', label: 'C++' },
  { value: 'java', label: 'Java' },
  { value: 'python', label: 'Python' },
  { value: 'javascript', label: 'JavaScript' },
  { value: 'typescript', label: 'TypeScript' },
];

const starterTemplates = {
  cpp: '#include <iostream>\n#include <vector>\nusing namespace std;\n\nint main() {\n    return 0;\n}\n',
  java: 'public class Solution {\n    public static void main(String[] args) {\n        \n    }\n}\n',
  python: 'def solve():\n    pass\n\n\nif __name__ == "__main__":\n    solve()\n',
  javascript: 'function solve() {\n  \n}\n',
  typescript: 'function solve(): void {\n  \n}\n',
};

const inferDefaultCodeLanguage = (prompt = '') => {
  const lower = prompt.toLowerCase();
  if (lower.includes('c++')) return 'cpp';
  if (lower.includes('java')) return 'java';
  if (lower.includes('typescript')) return 'typescript';
  if (lower.includes('javascript')) return 'javascript';
  return 'python';
};

const parseCodingExample = (content = '') => {
  if (!content) return null;

  const exampleLineMatch = content.match(/例如[:：]\s*([^\n]+)/);
  const exampleLine = exampleLineMatch?.[1] || '';
  const stdinMatch = content.match(/样例输入(?:\s*stdin)?[:：]\s*([\s\S]*?)(?:期望输出[:：]|输出[:：]|$)/);
  const outputMatch = content.match(/(?:期望输出|输出)[:：]\s*([^\n]+)/);

  if (stdinMatch || outputMatch) {
    return {
      title: '题目中的示例',
      stdin: (stdinMatch?.[1] || '').trim(),
      expectedOutput: (outputMatch?.[1] || '').trim(),
      sourceText: (exampleLine || content).trim(),
      language: inferDefaultCodeLanguage(content),
    };
  }

  const wordBreakMatch = exampleLine.match(/s\s*=\s*['"]([^'"]+)['"]\s*,\s*(?:dict|wordDict)\s*=\s*\[([^\]]*)\]\s*->\s*(true|false)/i);
  if (wordBreakMatch) {
    const [, sValue, dictRaw, result] = wordBreakMatch;
    const words = Array.from(dictRaw.matchAll(/['"]([^'"]+)['"]/g)).map((item) => item[1]).join(' ');
    return {
      title: '推荐测试用例',
      stdin: `${sValue}\n${words}`.trim(),
      expectedOutput: result.toLowerCase(),
      sourceText: exampleLine.trim(),
      language: 'python',
    };
  }

  return null;
};

const ChatInput = ({ onSendMessage, onRunCode, latestCodingPrompt = '', disabled = false }) => {
  const [mode, setMode] = useState('answer');
  const [message, setMessage] = useState('');
  const [codeLanguage, setCodeLanguage] = useState('cpp');
  const [codeValue, setCodeValue] = useState(starterTemplates.cpp);
  const [editorFullscreen, setEditorFullscreen] = useState(false);
  const [codeStdin, setCodeStdin] = useState('');
  const [expectedOutput, setExpectedOutput] = useState('');
  const [runResult, setRunResult] = useState(null);
  const [isRunningCode, setIsRunningCode] = useState(false);

  const suggestedTestCase = useMemo(
    () => parseCodingExample(latestCodingPrompt),
    [latestCodingPrompt],
  );

  const submitDisabled = useMemo(() => {
    if (disabled) return true;
    if (mode === 'answer') return !message.trim();
    return !codeValue.trim();
  }, [codeValue, disabled, message, mode]);

  const buildCodePayload = () => {
    const code = codeValue.trim();

    if (code) {
      return `这是我的代码实现：\n\n\`\`\`${codeLanguage}\n${code}\n\`\`\``;
    }
    return '';
  };

  const handleSubmit = (e) => {
    e.preventDefault();

    if (submitDisabled) {
      return;
    }

    if (mode === 'answer') {
      onSendMessage(message.trim());
      setMessage('');
      return;
    }

    onSendMessage(buildCodePayload());
  };

  const handleSwitchMode = (_, nextMode) => {
    if (!nextMode) return;
    setMode(nextMode);
  };

  const handleChangeLanguage = (event) => {
    const nextLanguage = event.target.value;
    setCodeLanguage(nextLanguage);
    if (!codeValue.trim() || codeValue === starterTemplates[codeLanguage]) {
      setCodeValue(starterTemplates[nextLanguage]);
    }
  };

  const handleInsertTemplate = () => {
    setCodeValue(starterTemplates[codeLanguage]);
  };

  const handleClearCode = () => {
    setCodeValue('');
  };

  const handleRunCode = async () => {
    if (!onRunCode || disabled || !codeValue.trim()) {
      return;
    }

    setIsRunningCode(true);
    setRunResult(null);

    try {
      const result = await onRunCode({
        language: codeLanguage,
        sourceCode: codeValue,
        stdin: codeStdin,
        expectedOutput,
      });
      setRunResult(result);
    } catch (error) {
      setRunResult({
        status: 'Failed',
        stdout: '',
        stderr: '',
        compile_output: '',
        message: error?.response?.data?.detail || error?.message || '运行失败，请稍后重试。',
        passed: null,
      });
    } finally {
      setIsRunningCode(false);
    }
  };

  useEffect(() => {
    if (!suggestedTestCase) return;

    if (!codeStdin.trim() && suggestedTestCase.stdin) {
      setCodeStdin(suggestedTestCase.stdin);
    }
    if (!expectedOutput.trim() && suggestedTestCase.expectedOutput) {
      setExpectedOutput(suggestedTestCase.expectedOutput);
    }
    if (!codeValue.trim()) {
      setCodeLanguage(suggestedTestCase.language || 'python');
      setCodeValue(starterTemplates[suggestedTestCase.language || 'python']);
    }
  }, [suggestedTestCase]);

  const monacoOptions = {
    minimap: { enabled: false },
    fontSize: 15,
    lineHeight: 24,
    roundedSelection: true,
    scrollBeyondLastLine: false,
    automaticLayout: true,
    wordWrap: 'off',
    tabSize: 2,
    padding: { top: 14, bottom: 14 },
    renderLineHighlight: 'all',
    guides: {
      indentation: true,
      bracketPairs: true,
    },
  };

  const renderCodeEditor = (height, sx = {}) => (
    <Box
      sx={{
        height,
        minHeight: 0,
        borderRadius: 1.0,
        overflow: 'hidden',
        border: '1px solid rgba(125, 211, 252, 0.18)',
        backgroundColor: 'rgba(8, 15, 28, 0.98)',
        boxShadow: 'inset 0 0 0 1px rgba(255,255,255,0.03)',
        ...sx,
      }}
    >
      <Editor
        height={height}
        language={codeLanguage}
        theme="vs-dark"
        value={codeValue}
        onChange={(value) => setCodeValue(value || '')}
        options={monacoOptions}
      />
    </Box>
  );

  const renderRunResult = () => {
    if (!runResult) return null;

    const outputText = runResult.stdout || runResult.stderr || runResult.compile_output || runResult.message || '本次运行没有输出内容。';
    const statusColor = runResult.status === 'Accepted'
      ? '#34d399'
      : runResult.status === 'Failed'
        ? '#f87171'
        : '#fbbf24';

    return (
      <Paper
        elevation={0}
        sx={{
          mt: 1.2,
          p: 1.5,
          borderRadius: 1.2,
          bgcolor: 'rgba(15, 23, 42, 0.92)',
          border: '1px solid rgba(125, 211, 252, 0.14)',
        }}
      >
        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" alignItems="center" sx={{ mb: 1 }}>
          <Chip
            size="small"
            label={`状态：${runResult.status || 'Unknown'}`}
            sx={{
              bgcolor: 'rgba(15, 23, 42, 0.88)',
              color: statusColor,
              border: `1px solid ${statusColor}33`,
            }}
          />
          {typeof runResult.passed === 'boolean' && (
            <Chip
              size="small"
              label={runResult.passed ? '样例通过' : '样例未通过'}
              sx={{
                bgcolor: runResult.passed ? 'rgba(52,211,153,0.12)' : 'rgba(248,113,113,0.12)',
                color: runResult.passed ? '#34d399' : '#f87171',
                border: '1px solid rgba(255,255,255,0.06)',
              }}
            />
          )}
          {runResult.time && (
            <Chip
              size="small"
              label={`耗时 ${runResult.time}s`}
              sx={{
                bgcolor: 'rgba(148,163,184,0.12)',
                color: '#cbd5e1',
              }}
            />
          )}
          {runResult.memory != null && (
            <Chip
              size="small"
              label={`内存 ${runResult.memory} KB`}
              sx={{
                bgcolor: 'rgba(148,163,184,0.12)',
                color: '#cbd5e1',
              }}
            />
          )}
        </Stack>

        <Typography variant="caption" sx={{ display: 'block', mb: 0.8, color: 'rgba(226,232,240,0.72)' }}>
          运行输出
        </Typography>
        <Box
          component="pre"
          sx={{
            m: 0,
            p: 1.4,
            borderRadius: 1,
            bgcolor: 'rgba(2, 6, 23, 0.96)',
            color: '#e2e8f0',
            fontSize: '0.85rem',
            lineHeight: 1.65,
            overflowX: 'auto',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            border: '1px solid rgba(255,255,255,0.04)',
          }}
        >
          {outputText}
        </Box>
      </Paper>
    );
  };

  const renderCodeRunPanel = () => (
    <Paper
      elevation={0}
      sx={{
        mt: 1.2,
        p: 1.2,
        borderRadius: 1.2,
        bgcolor: 'rgba(8, 15, 28, 0.88)',
        border: '1px solid rgba(125, 211, 252, 0.12)',
      }}
    >
      <Typography variant="subtitle2" sx={{ color: '#f8fafc', mb: 1 }}>
        代码调试区
      </Typography>

      {suggestedTestCase && (
        <Paper
          elevation={0}
          sx={{
            mb: 1.2,
            p: 1.2,
            borderRadius: 1.2,
            bgcolor: 'rgba(14, 165, 233, 0.08)',
            border: '1px solid rgba(125, 211, 252, 0.18)',
          }}
        >
          <Typography variant="subtitle2" sx={{ color: '#7dd3fc', mb: 0.6 }}>
            {suggestedTestCase.title}
          </Typography>
          {suggestedTestCase.sourceText && (
            <Typography
              variant="body2"
              sx={{
                color: 'rgba(226,232,240,0.82)',
                lineHeight: 1.7,
                mb: 1,
                wordBreak: 'keep-all',
                overflowWrap: 'break-word',
              }}
            >
              {suggestedTestCase.sourceText}
            </Typography>
          )}
          <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
            <Button
              variant="outlined"
              size="small"
              onClick={() => suggestedTestCase.stdin && setCodeStdin(suggestedTestCase.stdin)}
              sx={{
                borderColor: 'rgba(125, 211, 252, 0.28)',
                color: '#7dd3fc',
              }}
            >
              填入样例输入
            </Button>
            <Button
              variant="outlined"
              size="small"
              onClick={() => suggestedTestCase.expectedOutput && setExpectedOutput(suggestedTestCase.expectedOutput)}
              sx={{
                borderColor: 'rgba(52,211,153,0.28)',
                color: '#34d399',
              }}
            >
              填入期望输出
            </Button>
          </Stack>
        </Paper>
      )}

      <Stack direction={{ xs: 'column', md: 'row' }} spacing={1}>
        <TextField
          fullWidth
          label="样例输入 stdin"
          placeholder="例如：1 2 3"
          value={codeStdin}
          onChange={(e) => setCodeStdin(e.target.value)}
          disabled={disabled || isRunningCode}
          multiline
          minRows={3}
          maxRows={10}
          sx={{
            '& .MuiOutlinedInput-root': {
              borderRadius: 1.0,
              backgroundColor: 'rgba(15, 23, 42, 0.88)',
              color: '#f8fafc',
              alignItems: 'flex-start',
            },
            '& .MuiOutlinedInput-input': {
              lineHeight: 1.6,
              resize: 'vertical',
              overflow: 'auto !important',
            },
            '& .MuiOutlinedInput-notchedOutline': {
              borderColor: 'rgba(125, 211, 252, 0.14)',
            },
          }}
        />
        <TextField
          fullWidth
          label="期望输出"
          placeholder="可选，用于做简单通过判断"
          value={expectedOutput}
          onChange={(e) => setExpectedOutput(e.target.value)}
          disabled={disabled || isRunningCode}
          multiline
          minRows={3}
          maxRows={10}
          sx={{
            '& .MuiOutlinedInput-root': {
              borderRadius: 1.0,
              backgroundColor: 'rgba(15, 23, 42, 0.88)',
              color: '#f8fafc',
              alignItems: 'flex-start',
            },
            '& .MuiOutlinedInput-input': {
              lineHeight: 1.6,
              resize: 'vertical',
              overflow: 'auto !important',
            },
            '& .MuiOutlinedInput-notchedOutline': {
              borderColor: 'rgba(125, 211, 252, 0.14)',
            },
          }}
        />
      </Stack>

      {renderRunResult()}
    </Paper>
  );

  return (
    <Box
      component="form"
      onSubmit={handleSubmit}
      sx={{
        p: 2.5,
        borderTop: '1px solid rgba(125, 211, 252, 0.08)',
        background: 'rgba(8, 15, 28, 0.92)',
        backdropFilter: 'blur(12px)',
      }}
    >
      <Box
        sx={{
          display: 'flex',
          alignItems: { xs: 'flex-start', md: 'center' },
          justifyContent: 'space-between',
          gap: 1.5,
          mb: 1.5,
          flexDirection: { xs: 'column', md: 'row' },
        }}
      >
        <Tabs
          value={mode}
          onChange={handleSwitchMode}
          sx={{
            minHeight: 40,
            '& .MuiTabs-indicator': {
              height: 3,
              borderRadius: 999,
              backgroundColor: '#7dd3fc',
            },
          }}
        >
          <Tab
            value="answer"
            icon={<ChatBubbleOutlineRoundedIcon sx={{ fontSize: 18 }} />}
            iconPosition="start"
            label="普通作答"
            sx={{
              minHeight: 40,
              color: 'rgba(226,232,240,0.72)',
              '&.Mui-selected': { color: '#f8fafc' },
            }}
          />
          <Tab
            value="code"
            icon={<CodeRoundedIcon sx={{ fontSize: 18 }} />}
            iconPosition="start"
            label="代码作答"
            sx={{
              minHeight: 40,
              color: 'rgba(226,232,240,0.72)',
              '&.Mui-selected': { color: '#f8fafc' },
            }}
          />
        </Tabs>

        <Stack direction="row" spacing={0.8} useFlexGap flexWrap="wrap">
          <Chip
            size="small"
            label={mode === 'code' ? '支持粘贴代码块' : '支持自然语言回答'}
            sx={{
              bgcolor: 'rgba(125, 211, 252, 0.10)',
              color: '#7dd3fc',
              border: '1px solid rgba(125, 211, 252, 0.18)',
            }}
          />
          {mode === 'code' && (
            <Chip
              size="small"
              label="建议先讲思路再贴代码"
              sx={{
                bgcolor: 'rgba(245, 158, 11, 0.10)',
                color: '#fbbf24',
                border: '1px solid rgba(245, 158, 11, 0.18)',
              }}
            />
          )}
        </Stack>
      </Box>

      {mode === 'answer' ? (
        <Box sx={{ display: 'flex', alignItems: 'flex-end', gap: 1 }}>
          <TextField
            fullWidth
            placeholder="先说你的判断，再补充原因、细节和结果..."
            variant="outlined"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            disabled={disabled}
            multiline
            minRows={2}
            maxRows={5}
            sx={{
              '& .MuiOutlinedInput-root': {
                minHeight: 52,
                borderRadius: 1,
                backgroundColor: 'rgba(15, 23, 42, 0.88)',
                alignItems: 'center',
                color: '#f8fafc',
              },
              '& .MuiOutlinedInput-input': {
                padding: '14px 16px',
                lineHeight: 1.6,
              },
              '& .MuiOutlinedInput-notchedOutline': {
                borderColor: 'rgba(125, 211, 252, 0.14)',
              },
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSubmit(e);
              }
            }}
          />
          <IconButton
            color="primary"
            type="submit"
            disabled={submitDisabled}
            sx={{
              width: 68,
              minWidth: 68,
              minHeight: 52,
              alignSelf: 'stretch',
              borderRadius: 1,
              bgcolor: 'rgba(125, 211, 252, 0.14)',
              border: '1px solid rgba(125, 211, 252, 0.32)',
              boxShadow: 'inset 0 0 0 1px rgba(255,255,255,0.04)',
            }}
          >
            <SendRoundedIcon />
          </IconButton>
        </Box>
      ) : (
        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', lg: 'minmax(220px, 0.7fr) minmax(360px, 1.3fr) 72px' },
            gridTemplateRows: { xs: 'auto auto auto', lg: '300px' },
            gap: 1,
            alignItems: 'stretch',
          }}
        >
          <Box
            sx={{
              display: 'flex',
              flexDirection: 'column',
              gap: 1,
              minHeight: 0,
              overflowY: 'auto',
              pr: { xs: 0, lg: 0.5 },
            }}
          >
            <TextField
              select
              value={codeLanguage}
              onChange={handleChangeLanguage}
              disabled={disabled}
              size="small"
              sx={{
                '& .MuiOutlinedInput-root': {
                  borderRadius: 1.0,
                  bgcolor: 'rgba(15, 23, 42, 0.88)',
                  color: '#f8fafc',
                },
                '& .MuiOutlinedInput-notchedOutline': {
                  borderColor: 'rgba(125, 211, 252, 0.14)',
                },
              }}
            >
              {languageOptions.map((option) => (
                <MenuItem key={option.value} value={option.value}>
                  {option.label}
                </MenuItem>
              ))}
            </TextField>

            <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
              <Button
                variant="outlined"
                size="small"
                startIcon={<DeleteOutlineRoundedIcon />}
                onClick={handleClearCode}
                disabled={disabled || !codeValue.trim()}
                sx={{
                  borderColor: 'rgba(248, 113, 113, 0.28)',
                  color: '#fca5a5',
                }}
              >
                清空代码
              </Button>
              <Button
                variant="outlined"
                size="small"
                startIcon={<PostAddRoundedIcon />}
                onClick={handleInsertTemplate}
                disabled={disabled}
                sx={{
                  borderColor: 'rgba(125, 211, 252, 0.28)',
                  color: '#7dd3fc',
                }}
              >
                插入模板
              </Button>
              <Button
                variant="outlined"
                size="small"
                startIcon={<OpenInFullRoundedIcon />}
                onClick={() => setEditorFullscreen(true)}
                disabled={disabled}
                sx={{
                  borderColor: 'rgba(196, 181, 253, 0.28)',
                  color: '#c4b5fd',
                }}
              >
                全屏写代码
              </Button>
              <Button
                variant="contained"
                size="small"
                startIcon={<PlayArrowRoundedIcon />}
                onClick={handleRunCode}
                disabled={disabled || isRunningCode || !codeValue.trim()}
                sx={{
                  bgcolor: '#0ea5e9',
                  color: '#04101c',
                  '&:hover': {
                    bgcolor: '#0284c7',
                  },
                }}
              >
                {isRunningCode ? '运行中...' : '运行代码'}
              </Button>
            </Stack>

            {renderCodeRunPanel()}
          </Box>

          {renderCodeEditor(300)}

          <IconButton
            color="primary"
            type="submit"
            disabled={submitDisabled}
            sx={{
              width: { xs: '100%', lg: 72 },
              minWidth: { xs: '100%', lg: 72 },
              height: { xs: 52, lg: '100%' },
              borderRadius: 1.0,
              bgcolor: 'rgba(125, 211, 252, 0.14)',
              border: '1px solid rgba(125, 211, 252, 0.32)',
              boxShadow: 'inset 0 0 0 1px rgba(255,255,255,0.04)',
              alignSelf: 'stretch',
            }}
          >
            <SendRoundedIcon />
          </IconButton>
        </Box>
      )}

      {mode === 'code' && (
        <Typography
          variant="caption"
          sx={{
            mt: 1,
            display: 'block',
            color: 'rgba(226,232,240,0.62)',
            lineHeight: 1.7,
          }}
        >
          发送时会自动包装成 Markdown 代码块，面试官会基于你的代码实现继续追问。
        </Typography>
      )}

      <Dialog
        open={editorFullscreen}
        onClose={() => setEditorFullscreen(false)}
        fullScreen
        PaperProps={{
          sx: {
            bgcolor: '#020617',
            backgroundImage: 'linear-gradient(180deg, rgba(8,15,28,0.96) 0%, rgba(2,6,23,1) 100%)',
          },
        }}
      >
        <Box
          sx={{
            px: { xs: 2, md: 3 },
            py: 1.5,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 1.5,
            borderBottom: '1px solid rgba(125, 211, 252, 0.12)',
          }}
        >
          <Box>
            <Typography variant="h6" sx={{ color: '#f8fafc', fontWeight: 700 }}>
              代码作答工作区
            </Typography>
            <Typography variant="body2" sx={{ color: 'rgba(226,232,240,0.68)' }}>
              直接写代码并运行调试，发送时会自动保留语言标记。
            </Typography>
          </Box>

          <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
            <Button
              variant="outlined"
              size="small"
              startIcon={<DeleteOutlineRoundedIcon />}
              onClick={handleClearCode}
              disabled={disabled || !codeValue.trim()}
              sx={{
                borderColor: 'rgba(248, 113, 113, 0.28)',
                color: '#fca5a5',
              }}
            >
              清空代码
            </Button>
            <Button
              variant="outlined"
              size="small"
              startIcon={<PostAddRoundedIcon />}
              onClick={handleInsertTemplate}
              disabled={disabled}
              sx={{
                borderColor: 'rgba(125, 211, 252, 0.28)',
                color: '#7dd3fc',
              }}
            >
              插入模板
            </Button>
            <Button
              variant="outlined"
              size="small"
              startIcon={<CloseFullscreenRoundedIcon />}
              onClick={() => setEditorFullscreen(false)}
              sx={{
                borderColor: 'rgba(196, 181, 253, 0.28)',
                color: '#c4b5fd',
              }}
            >
              退出全屏
            </Button>
            <Button
              variant="contained"
              size="small"
              startIcon={<PlayArrowRoundedIcon />}
              onClick={handleRunCode}
              disabled={disabled || isRunningCode || !codeValue.trim()}
              sx={{
                bgcolor: '#0ea5e9',
                color: '#04101c',
                '&:hover': {
                  bgcolor: '#0284c7',
                },
              }}
            >
              {isRunningCode ? '运行中...' : '运行代码'}
            </Button>
          </Stack>
        </Box>

        <DialogContent
          sx={{
            p: { xs: 2, md: 3 },
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', lg: 'minmax(280px, 0.7fr) minmax(560px, 1.3fr)' },
            gridTemplateRows: 'minmax(0, 1fr)',
            gap: 2,
            alignItems: 'stretch',
            height: 'calc(100vh - 82px)',
            minHeight: 0,
          }}
        >
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, minHeight: 0, overflow: 'auto' }}>
            <TextField
              select
              value={codeLanguage}
              onChange={handleChangeLanguage}
              disabled={disabled}
              size="small"
              sx={{
                '& .MuiOutlinedInput-root': {
                  borderRadius: 1.0,
                  bgcolor: 'rgba(15, 23, 42, 0.88)',
                  color: '#f8fafc',
                },
                '& .MuiOutlinedInput-notchedOutline': {
                  borderColor: 'rgba(125, 211, 252, 0.14)',
                },
              }}
            >
              {languageOptions.map((option) => (
                <MenuItem key={option.value} value={option.value}>
                  {option.label}
                </MenuItem>
              ))}
            </TextField>

            <Button
              variant="contained"
              type="button"
              startIcon={<SendRoundedIcon />}
              onClick={() => onSendMessage(buildCodePayload())}
              disabled={submitDisabled}
              sx={{
                alignSelf: 'flex-start',
                borderRadius: 1.0,
                px: 2,
                bgcolor: '#0284c7',
                '&:hover': {
                  bgcolor: '#0369a1',
                },
              }}
            >
              发送代码作答
            </Button>

            <Divider sx={{ borderColor: 'rgba(125, 211, 252, 0.10)' }} />

            {renderCodeRunPanel()}
          </Box>

          {renderCodeEditor('100%', { alignSelf: 'stretch' })}
        </DialogContent>
      </Dialog>
    </Box>
  );
};

export default ChatInput;
