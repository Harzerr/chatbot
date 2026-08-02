import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { ThemeProvider, createTheme, CssBaseline } from '@mui/material';
import { AuthProvider } from './contexts/AuthContext';
import { LiveKitProvider } from './contexts/LiveKitContext';
import ProtectedRoute from './components/ProtectedRoute';
import Login from './pages/Login';
import Register from './pages/Register';
import Chat from './pages/Chat';
import VoiceAssistantPage from './pages/VoiceAssistantPage';
import Profile from './pages/Profile';
import CareerStudio from './pages/CareerStudio';
import TrainingCamp from './pages/TrainingCamp';

const interviewTheme = createTheme({
  palette: {
    mode: 'light',
    primary: {
      main: '#0284c7',
    },
    secondary: {
      main: '#d97706',
    },
    background: {
      default: '#f4f7fb',
      paper: '#ffffff',
    },
    success: {
      main: '#059669',
    },
    warning: {
      main: '#d97706',
    },
    text: {
      primary: '#0f172a',
      secondary: '#475569',
    },
  },
  shape: {
    borderRadius: 18,
  },
  typography: {
    fontFamily: '"IBM Plex Sans", "Segoe UI", sans-serif',
    h4: {
      fontWeight: 700,
      letterSpacing: '-0.03em',
    },
    h5: {
      fontWeight: 700,
      letterSpacing: '-0.02em',
    },
    h6: {
      fontWeight: 600,
    },
    button: {
      textTransform: 'none',
      fontWeight: 600,
    },
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: {
          background:
            'linear-gradient(180deg, #f8fbff 0%, #eef4fb 100%)',
          scrollbarColor: '#cbd5e1 #f8fafc',
          '&::-webkit-scrollbar, & *::-webkit-scrollbar': {
            backgroundColor: '#f8fafc',
            width: 10,
            height: 10,
          },
          '&::-webkit-scrollbar-thumb, & *::-webkit-scrollbar-thumb': {
            borderRadius: 10,
            backgroundColor: '#cbd5e1',
          },
          '&::-webkit-scrollbar-thumb:hover, & *::-webkit-scrollbar-thumb:hover': {
            backgroundColor: '#94a3b8',
          },
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          border: '1px solid rgba(148, 163, 184, 0.18)',
        },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          background: 'rgba(255, 255, 255, 0.86)',
          backdropFilter: 'blur(16px)',
          borderBottom: '1px solid rgba(148, 163, 184, 0.18)',
          boxShadow: '0 10px 30px rgba(15, 23, 42, 0.06)',
          color: '#0f172a',
        },
      },
    },
  },
});

const App = () => {
  return (
    <ThemeProvider theme={interviewTheme}>
      <CssBaseline />
      <AuthProvider>
        <LiveKitProvider>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />
            <Route element={<ProtectedRoute />}>
              <Route path="/chat" element={<Chat />} />
              <Route path="/profile" element={<Profile />} />
              <Route path="/career" element={<CareerStudio />} />
              <Route path="/training" element={<TrainingCamp />} />
              <Route path="/voice" element={<VoiceAssistantPage />} />
            </Route>
            <Route path="*" element={<Navigate to="/chat" replace />} />
          </Routes>
        </LiveKitProvider>
      </AuthProvider>
    </ThemeProvider>
  );
};

export default App;
