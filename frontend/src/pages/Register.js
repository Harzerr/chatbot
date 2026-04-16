import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import {
  Box,
  TextField,
  Button,
  Typography,
  Paper,
  Container,
  Alert,
  CircularProgress,
  Link as MuiLink,
} from '@mui/material';
import { useAuth } from '../contexts/AuthContext';

/**
 * Registration page component
 */
const Register = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [tenantId, setTenantId] = useState('');
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [targetRole, setTargetRole] = useState('');
  const [yearsOfExperience, setYearsOfExperience] = useState('');
  const [bio, setBio] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [validationError, setValidationError] = useState('');
  const { register, error } = useAuth();
  const navigate = useNavigate();

  /**
   * Handle form submission
   * @param {React.FormEvent} e - Form event
   */
  const handleSubmit = async (e) => {
    e.preventDefault();

    if (!username.trim() || !password.trim() || !confirmPassword.trim() || !tenantId.trim() || !fullName.trim() || !email.trim() || !phone.trim() || !targetRole.trim() || yearsOfExperience === '') {
      setValidationError('请完整填写注册信息');
      return;
    }
    
    if (password !== confirmPassword) {
      setValidationError('Passwords do not match');
      return;
    }
    
    setValidationError('');
    setIsSubmitting(true);
    
    try {
      await register({
        username,
        password,
        tenant_id: tenantId,
        full_name: fullName,
        email,
        phone,
        target_role: targetRole,
        years_of_experience: Number(yearsOfExperience),
        bio,
      });
      navigate('/login', { 
        state: { 
          registrationSuccess: true,
          message: '注册成功，请登录后先完善个人档案并上传简历。' 
        } 
      });
    } catch (err) {
      console.error('Registration error:', err);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Container maxWidth="sm">
      <Box
        sx={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '100vh',
        }}
      >
        <Paper
          elevation={3}
          sx={{
            p: 4,
            width: '100%',
            borderRadius: 2,
            bgcolor: 'background.paper',
          }}
        >
          <Typography variant="h4" component="h1" align="center" gutterBottom>
            LangGraph Chatbot
          </Typography>
          
          <Typography variant="h6" component="h2" align="center" gutterBottom>
            Create Account
          </Typography>
          
          {(error || validationError) && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {error || validationError}
            </Alert>
          )}
          
          <Box component="form" onSubmit={handleSubmit} noValidate>
            <TextField
              margin="normal"
              required
              fullWidth
              id="fullName"
              label="姓名"
              name="fullName"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              disabled={isSubmitting}
            />

            <TextField
              margin="normal"
              required
              fullWidth
              id="email"
              label="邮箱"
              name="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={isSubmitting}
            />

            <TextField
              margin="normal"
              required
              fullWidth
              id="phone"
              label="手机号"
              name="phone"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              disabled={isSubmitting}
            />

            <TextField
              margin="normal"
              required
              fullWidth
              id="targetRole"
              label="目标岗位"
              name="targetRole"
              value={targetRole}
              onChange={(e) => setTargetRole(e.target.value)}
              disabled={isSubmitting}
            />

            <TextField
              margin="normal"
              required
              fullWidth
              id="yearsOfExperience"
              label="工作年限"
              name="yearsOfExperience"
              type="number"
              inputProps={{ min: 0, max: 50 }}
              value={yearsOfExperience}
              onChange={(e) => setYearsOfExperience(e.target.value)}
              disabled={isSubmitting}
            />

            <TextField
              margin="normal"
              fullWidth
              id="bio"
              label="个人简介"
              name="bio"
              multiline
              minRows={3}
              value={bio}
              onChange={(e) => setBio(e.target.value)}
              disabled={isSubmitting}
            />

            <TextField
              margin="normal"
              required
              fullWidth
              id="username"
              label="Username"
              name="username"
              autoComplete="username"
              autoFocus
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              disabled={isSubmitting}
            />
            
            <TextField
              margin="normal"
              required
              fullWidth
              name="password"
              label="Password"
              type="password"
              id="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={isSubmitting}
            />
            
            <TextField
              margin="normal"
              required
              fullWidth
              name="confirmPassword"
              label="Confirm Password"
              type="password"
              id="confirmPassword"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              disabled={isSubmitting}
            />
            
            <TextField
              margin="normal"
              required
              fullWidth
              name="tenantId"
              label="Tenant ID"
              id="tenantId"
              helperText="Unique identifier for your organization or project"
              value={tenantId}
              onChange={(e) => setTenantId(e.target.value)}
              disabled={isSubmitting}
            />
            
            <Button
              type="submit"
              fullWidth
              variant="contained"
              sx={{ mt: 3, mb: 2 }}
              disabled={
                isSubmitting
                || !username.trim()
                || !password.trim()
                || !confirmPassword.trim()
                || !tenantId.trim()
                || !fullName.trim()
                || !email.trim()
                || !phone.trim()
                || !targetRole.trim()
                || yearsOfExperience === ''
              }
            >
              {isSubmitting ? <CircularProgress size={24} /> : 'Register'}
            </Button>
            
            <Box sx={{ textAlign: 'center' }}>
              <MuiLink component={Link} to="/login" variant="body2">
                Already have an account? Sign in
              </MuiLink>
            </Box>
          </Box>
        </Paper>
      </Box>
    </Container>
  );
};

export default Register;
