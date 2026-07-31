import axios from 'axios';

const trainingService = {
  list: async () => (await axios.get('/api/v1/training/items')).data,
  createDefaultPlan: async (jobId = null) => (await axios.post('/api/v1/training/plans/default', { job_id: jobId || null })).data,
  answer: async (id, answer) => (await axios.post(`/api/v1/training/items/${id}/answer`, { answer })).data,
  setStatus: async (id, status) => (await axios.patch(`/api/v1/training/items/${id}/status`, { status })).data,
  remove: async (id) => axios.delete(`/api/v1/training/items/${id}`),
};

export default trainingService;
