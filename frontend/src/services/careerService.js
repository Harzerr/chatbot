import axios from 'axios';

const careerService = {
  listFacts: async () => (await axios.get('/api/v1/career/facts')).data,
  createFact: async (payload) => (await axios.post('/api/v1/career/facts', payload)).data,
  updateFact: async (id, payload) => (await axios.put(`/api/v1/career/facts/${id}`, payload)).data,
  archiveFact: async (id) => (await axios.delete(`/api/v1/career/facts/${id}`)).data,
  deleteFact: async (id) => (await axios.delete(`/api/v1/career/facts/${id}/permanently`)).data,
  extractFacts: async () => (await axios.post('/api/v1/career/facts/extract')).data,
  extractFactFromMarkdown: async (file) => {
    const formData = new FormData();
    formData.append('file', file);
    return (await axios.post('/api/v1/career/facts/extract-from-markdown', formData)).data;
  },
  getMarkdownFactJob: async (jobId) => (await axios.get(`/api/v1/career/facts/extract-from-markdown/jobs/${jobId}`)).data,
  listKnowledgeDocuments: async () => (await axios.get('/api/v1/career/documents')).data,
  uploadKnowledgeDocument: async ({ file, factId, title }) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('fact_id', String(factId));
    if (title) formData.append('title', title);
    return (await axios.post('/api/v1/career/documents/upload', formData)).data;
  },
  updateKnowledgeDocument: async (id, payload) => (await axios.put(`/api/v1/career/documents/${id}`, payload)).data,
  archiveKnowledgeDocument: async (id) => (await axios.delete(`/api/v1/career/documents/${id}`)).data,
  importProfile: async (draft) => (await axios.post('/api/v1/career/profile/import', { draft })).data,
  listJobs: async () => (await axios.get('/api/v1/career/jobs')).data,
  importJob: async (payload) => (await axios.post('/api/v1/career/jobs/import', payload)).data,
  updateJob: async (id, payload) => (await axios.put(`/api/v1/career/jobs/${id}`, payload)).data,
  refreshJob: async (id) => (await axios.post(`/api/v1/career/jobs/${id}/refresh`)).data,
  deleteJob: async (id) => (await axios.delete(`/api/v1/career/jobs/${id}`)).data,
  listResumes: async () => (await axios.get('/api/v1/career/resumes')).data,
  generateResume: async (payload) => (await axios.post('/api/v1/career/resumes/generate', payload)).data,
  downloadResumeTex: async (id) => axios.get(`/api/v1/career/resumes/${id}/tex`, { responseType: 'blob' }),
  downloadResumePdf: async (id) => axios.get(`/api/v1/career/resumes/${id}/pdf`, { responseType: 'blob' }),
  updateResume: async (id, payload) => (await axios.put(`/api/v1/career/resumes/${id}`, payload)).data,
  deleteResume: async (id) => (await axios.delete(`/api/v1/career/resumes/${id}`)).data,
};

export default careerService;
