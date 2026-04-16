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

const interviewTheme = createTheme({
  palette: {
    mode: 'dark',
    primary: {
      main: '#7dd3fc',
    },
    secondary: {
      main: '#f59e0b',
    },
    background: {
      default: '#07111f',
      paper: '#0d1728',
    },
    success: {
      main: '#34d399',
    },
    warning: {
      main: '#fbbf24',
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
            'radial-gradient(circle at top left, rgba(14,165,233,0.18), transparent 30%), radial-gradient(circle at top right, rgba(245,158,11,0.12), transparent 24%), linear-gradient(180deg, #07111f 0%, #0a1322 100%)',
          scrollbarColor: '#3b4c68 #0d1728',
          '&::-webkit-scrollbar, & *::-webkit-scrollbar': {
            backgroundColor: '#0d1728',
            width: 10,
            height: 10,
          },
          '&::-webkit-scrollbar-thumb, & *::-webkit-scrollbar-thumb': {
            borderRadius: 10,
            backgroundColor: '#36506b',
          },
          '&::-webkit-scrollbar-thumb:hover, & *::-webkit-scrollbar-thumb:hover': {
            backgroundColor: '#4d6a88',
          },
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          border: '1px solid rgba(125, 211, 252, 0.08)',
        },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          background: 'rgba(7, 17, 31, 0.78)',
          backdropFilter: 'blur(16px)',
          borderBottom: '1px solid rgba(125, 211, 252, 0.10)',
          boxShadow: 'none',
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
