import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  AppBar,
  Box,
  Button,
  Chip,
  CircularProgress,
  Container,
  Paper,
  Stack,
  TextField,
  Toolbar,
  Typography,
} from '@mui/material';
import ArrowBackRoundedIcon from '@mui/icons-material/ArrowBackRounded';
import DescriptionRoundedIcon from '@mui/icons-material/DescriptionRounded';
import UploadFileRoundedIcon from '@mui/icons-material/UploadFileRounded';
import SaveRoundedIcon from '@mui/icons-material/SaveRounded';
import LogoutIcon from '@mui/icons-material/Logout';
import { useAuth } from '../contexts/AuthContext';
import chatService from '../services/chatService';
import ProfileGrowthReport from '../components/ProfileGrowthReport';

const HISTORY_PAGE_SIZE = 100;
const HISTORY_MAX_PAGES = 20;

const Profile = () => {
  const navigate = useNavigate();
  const {
    currentUser,
    loading,
    error,
    refreshCurrentUser,
    updateProfile,
    uploadResume,
    logout,
  } = useAuth();

  const [form, setForm] = useState({
    username: '',
    full_name: '',
    email: '',
    phone: '',
    target_role: '',
    years_of_experience: 0,
    bio: '',
  });
  const [saveLoading, setSaveLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState('');
  const [growthLoading, setGrowthLoading] = useState(false);
  const [growthError, setGrowthError] = useState('');
  const [interviewMessages, setInterviewMessages] = useState([]);

  const loadGrowthReport = useCallback(async () => {
    setGrowthLoading(true);
    setGrowthError('');
    try {
      const allMessages = [];

      for (let page = 0; page < HISTORY_MAX_PAGES; page += 1) {
        const offset = page * HISTORY_PAGE_SIZE;
        const response = await chatService.getUserChats(HISTORY_PAGE_SIZE, offset);
        const batch = Array.isArray(response?.messages) ? response.messages : [];

        allMessages.push(...batch);

        if (batch.length < HISTORY_PAGE_SIZE) {
          break;
        }
      }

      setInterviewMessages(allMessages);
    } catch (err) {
      console.error('Failed to load growth report data:', err);
      setGrowthError('加载成长分析数据失败，请稍后重试。');
    } finally {
      setGrowthLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshCurrentUser().catch((err) => {
      console.error('Failed to refresh profile:', err);
    });
  }, [refreshCurrentUser]);

  useEffect(() => {
    loadGrowthReport().catch((err) => {
      console.error('Failed to initialize growth report:', err);
    });
  }, [loadGrowthReport]);

  useEffect(() => {
    if (!currentUser) return;
    setForm({
      username: currentUser.username || '',
      full_name: currentUser.full_name || '',
      email: currentUser.email || '',
      phone: currentUser.phone || '',
      target_role: currentUser.target_role || '',
      years_of_experience: currentUser.years_of_experience ?? 0,
      bio: currentUser.bio || '',
    });
  }, [currentUser]);

  const handleChange = (field) => (event) => {
    const value = field === 'years_of_experience' ? Number(event.target.value) : event.target.value;
    setForm((prev) => ({ ...prev, [field]: value }));
  };

  const handleSave = async (event) => {
    event.preventDefault();
    setMessage('');
    setSaveLoading(true);
    try {
      await updateProfile(form);
      setMessage('个人档案已更新。');
    } catch (err) {
      console.error('Profile save failed:', err);
    } finally {
      setSaveLoading(false);
    }
  };

  const handleResumeUpload = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;

    setMessage('');
    setUploading(true);
    try {
      const response = await uploadResume(file);
      setMessage(`简历上传成功，系统已完成解析。文件：${response.file_name}`);
      await loadGrowthReport();
    } catch (err) {
      console.error('Resume upload failed:', err);
    } finally {
      setUploading(false);
      event.target.value = '';
    }
  };

  if (loading && !currentUser) {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100vh' }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box sx={{ minHeight: '100vh' }}>
      <AppBar position="sticky">
        <Toolbar sx={{ gap: 1.5 }}>
          <Button color="inherit" startIcon={<ArrowBackRoundedIcon />} onClick={() => navigate('/chat')}>
            返回面试
          </Button>
          <Box sx={{ flexGrow: 1 }}>
            <Typography variant="h6">个人档案</Typography>
          </Box>
          <Button
            color="inherit"
            onClick={() => {
              logout();
              navigate('/login');
            }}
            startIcon={<LogoutIcon />}
          >
            退出登录
          </Button>
        </Toolbar>
      </AppBar>

      <Container maxWidth="lg" sx={{ py: 4 }}>
        <Stack spacing={3}>
          {(error || message) && (
            <Alert severity={error ? 'error' : 'success'}>
              {error || message}
            </Alert>
          )}

          <Paper elevation={0} sx={{ p: 3, borderRadius: 3 }}>
            <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} justifyContent="space-between">
              <Box>
                <Typography variant="h5" sx={{ fontWeight: 700 }}>
                  候选人资料
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1, maxWidth: 720, lineHeight: 1.7 }}>
                  这里的注册资料会影响面试上下文。上传简历后，系统会根据你的项目经历、技能栈和目标岗位生成更贴合的提问。
                </Typography>
              </Box>
              <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                <Chip
                  icon={<DescriptionRoundedIcon />}
                  label={currentUser?.has_resume ? `已上传简历：${currentUser.resume_file_name}` : '尚未上传简历'}
                  sx={{
                    bgcolor: currentUser?.has_resume ? 'rgba(52,211,153,0.14)' : 'rgba(245,158,11,0.12)',
                    color: currentUser?.has_resume ? '#34d399' : '#fbbf24',
                  }}
                />
              </Stack>
            </Stack>
          </Paper>

          <Stack direction={{ xs: 'column', lg: 'row' }} spacing={3} alignItems="stretch">
            <Paper elevation={0} sx={{ p: 3, borderRadius: 3, flex: 1.2 }}>
              <Typography variant="h6" sx={{ mb: 2 }}>
                基础信息
              </Typography>
              <Box component="form" onSubmit={handleSave}>
                <Stack spacing={2}>
                  <TextField label="用户名" value={form.username} onChange={handleChange('username')} fullWidth />
                  <TextField label="姓名" value={form.full_name} onChange={handleChange('full_name')} fullWidth />
                  <TextField label="邮箱" type="email" value={form.email} onChange={handleChange('email')} fullWidth />
                  <TextField label="手机号" value={form.phone} onChange={handleChange('phone')} fullWidth />
                  <TextField label="目标岗位" value={form.target_role} onChange={handleChange('target_role')} fullWidth />
                  <TextField
                    label="工作年限"
                    type="number"
                    inputProps={{ min: 0, max: 50 }}
                    value={form.years_of_experience}
                    onChange={handleChange('years_of_experience')}
                    fullWidth
                  />
                  <TextField
                    label="个人简介"
                    value={form.bio}
                    onChange={handleChange('bio')}
                    fullWidth
                    multiline
                    minRows={5}
                  />
                  <Button type="submit" variant="contained" startIcon={<SaveRoundedIcon />} disabled={saveLoading}>
                    {saveLoading ? '保存中...' : '保存档案'}
                  </Button>
                </Stack>
              </Box>
            </Paper>

            <Paper elevation={0} sx={{ p: 3, borderRadius: 3, flex: 1 }}>
              <Typography variant="h6" sx={{ mb: 2 }}>
                简历上传
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.75 }}>
                支持上传 PDF、PNG、JPG、JPEG、WEBP。上传后系统会自动提取简历文本，用于后续模拟面试提问。
              </Typography>

              <Button
                component="label"
                variant="outlined"
                startIcon={<UploadFileRoundedIcon />}
                disabled={uploading}
                sx={{ mt: 2, borderRadius: 2 }}
              >
                {uploading ? '上传并解析中...' : '上传简历'}
                <input
                  hidden
                  type="file"
                  accept=".pdf,image/png,image/jpeg,image/jpg,image/webp"
                  onChange={handleResumeUpload}
                />
              </Button>

              <Paper
                elevation={0}
                sx={{
                  mt: 2.5,
                  p: 2,
                  borderRadius: 2,
                  bgcolor: 'rgba(255,255,255,0.03)',
                  border: '1px solid rgba(125,211,252,0.10)',
                }}
              >
                <Typography variant="subtitle2" sx={{ color: '#f8fafc', mb: 1 }}>
                  当前简历状态
                </Typography>
                {currentUser?.has_resume ? (
                  <>
                    <Typography variant="body2" sx={{ color: '#e2e8f0', lineHeight: 1.8 }}>
                      文件名：{currentUser.resume_file_name}
                    </Typography>
                    <Typography variant="body2" sx={{ color: '#94a3b8', lineHeight: 1.8 }}>
                      上传时间：{currentUser.resume_uploaded_at}
                    </Typography>
                    <Typography variant="body2" sx={{ color: '#e2e8f0', mt: 1.2, lineHeight: 1.8, whiteSpace: 'pre-wrap' }}>
                      {currentUser.resume_excerpt}
                    </Typography>
                  </>
                ) : (
                  <Typography variant="body2" sx={{ color: '#fbbf24', lineHeight: 1.8 }}>
                    还没有上传简历。开始新面试前建议先上传简历。
                  </Typography>
                )}
              </Paper>
            </Paper>
          </Stack>

          <ProfileGrowthReport
            messages={interviewMessages}
            loading={growthLoading}
            error={growthError}
            onRetry={loadGrowthReport}
          />
        </Stack>
      </Container>
    </Box>
  );
};

export default Profile;
