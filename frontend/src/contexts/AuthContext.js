import React, { createContext, useState, useContext, useEffect } from 'react';
import axios from 'axios';
import userService from '../services/userService';

/**
 * Authentication context for managing user authentication state
 */
const AuthContext = createContext(null);

/**
 * Authentication provider component
 * @param {Object} props - Component props
 * @param {React.ReactNode} props.children - Child components
 */
export const AuthProvider = ({ children }) => {
  const [token, setToken] = useState(null);
  const [tokenType, setTokenType] = useState('Bearer');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [currentUser, setCurrentUser] = useState(null);

  useEffect(() => {
    const storedToken = localStorage.getItem('token');
    const storedTokenType = localStorage.getItem('token_type') || 'Bearer';

    const bootstrapAuth = async () => {
      if (storedToken) {
        setToken(storedToken);
        setTokenType(storedTokenType);
        axios.defaults.headers.common['Authorization'] = `${storedTokenType} ${storedToken}`;

        try {
          const profile = await userService.getMe();
          setCurrentUser(profile);
        } catch (err) {
          console.error('Failed to restore session profile:', err);
          localStorage.removeItem('token');
          localStorage.removeItem('token_type');
          delete axios.defaults.headers.common['Authorization'];
          setToken(null);
          setTokenType('Bearer');
          setCurrentUser(null);
        }
      }

      setLoading(false);
    };

    bootstrapAuth();
  }, []);

  /**
   * Login user with username and password
   * @param {string} username - User's username
   * @param {string} password - User's password
   * @returns {Promise<string>} - JWT token
   */
  const login = async (username, password) => {
    setError(null);
    try {
      const formData = new URLSearchParams();
      formData.append('grant_type', 'password');
      formData.append('username', username);
      formData.append('password', password);
      formData.append('scope', '');
      formData.append('client_id', 'string');
      formData.append('client_secret', 'string');
      
      const response = await axios.post('/api/v1/auth/login', formData, {
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
        },
      });
      
      const { access_token, token_type } = response.data;

      localStorage.setItem('token', access_token);
      localStorage.setItem('token_type', token_type);
      axios.defaults.headers.common['Authorization'] = `${token_type} ${access_token}`;
      const profile = await userService.getMe();

      setToken(access_token);
      setTokenType(token_type);
      setCurrentUser(profile);
      return access_token;
    } catch (err) {
      console.error('Login failed:', err);
      setError(err.response?.data?.detail || 'Login failed. Please check your credentials.');
      throw err;
    }
  };

  /**
   * Logout user
   */
  const logout = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('token_type');
    delete axios.defaults.headers.common['Authorization'];
    setToken(null);
    setTokenType('Bearer');
    setCurrentUser(null);
  };

  /**
   * Register a new user
   * @param {string} username - User's username
   * @param {string} password - User's password
   * @param {string} tenantId - User's tenant ID
   * @returns {Promise<Object>} - Registration response
   */
  const register = async (payload) => {
    setError(null);
    try {
      const response = await axios.post('/api/v1/auth/register', payload);
      
      return response.data;
    } catch (err) {
      console.error('Registration failed:', err);
      setError(err.response?.data?.detail || 'Registration failed. Please try again.');
      throw err;
    }
  };

  const refreshCurrentUser = async () => {
    const profile = await userService.getMe();
    setCurrentUser(profile);
    return profile;
  };

  const updateProfile = async (payload) => {
    setError(null);
    try {
      const profile = await userService.updateMe(payload);
      setCurrentUser(profile);
      return profile;
    } catch (err) {
      console.error('Profile update failed:', err);
      setError(err.response?.data?.detail || 'Profile update failed. Please try again.');
      throw err;
    }
  };

  const uploadResume = async (file) => {
    setError(null);
    try {
      const response = await userService.uploadResume(file);
      await refreshCurrentUser();
      return response;
    } catch (err) {
      console.error('Resume upload failed:', err);
      setError(err.response?.data?.detail || 'Resume upload failed. Please try again.');
      throw err;
    }
  };

  const value = {
    isAuthenticated: !!token,
    token,
    tokenType,
    currentUser,
    loading,
    error,
    login,
    logout,
    register,
    refreshCurrentUser,
    updateProfile,
    uploadResume,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

/**
 * Hook to use authentication context
 * @returns {Object} Authentication context
 */
export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
