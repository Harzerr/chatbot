import axios from 'axios';

const userService = {
  getMe: async () => {
    const response = await axios.get('/api/v1/users/me');
    return response.data;
  },

  updateMe: async (payload) => {
    const response = await axios.put('/api/v1/users/me', payload);
    return response.data;
  },

  uploadAvatar: async (file) => {
    const formData = new FormData();
    formData.append('file', file);
    const response = await axios.post('/api/v1/users/me/avatar', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data;
  },

  deleteAvatar: async () => axios.delete('/api/v1/users/me/avatar'),

  uploadResume: async (file) => {
    const formData = new FormData();
    formData.append('file', file);
    const response = await axios.post('/api/v1/users/me/resume', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return response.data;
  },

  getResumeParseJob: async (jobId) => {
    const response = await axios.get(`/api/v1/users/me/resume/jobs/${jobId}`);
    return response.data;
  },

  retryResumeParseJob: async (jobId) => {
    const response = await axios.post(`/api/v1/users/me/resume/jobs/${jobId}/retry`);
    return response.data;
  },
};

export default userService;
