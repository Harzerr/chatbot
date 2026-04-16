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
};

export default userService;
