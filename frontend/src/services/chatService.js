import axios from 'axios';

/**
 * Service for interacting with chat API endpoints
 */
const chatService = {
  /**
   * Get all chats for the current user
   * @param {number} limit - Maximum number of chats to retrieve (default: 50)
   * @param {number} offset - Offset for pagination (default: 0)
   * @returns {Promise<Object>} Chat history response with messages and total count
   */
  getUserChats: async (limit = 50, offset = 0) => {
    try {
      const response = await axios.get(`/api/v1/history/chats?limit=${limit}&offset=${offset}`);
      return response.data;
    } catch (error) {
      console.error('Error fetching user chats:', error);
      throw error;
    }
  },

  /**
   * Get messages for a specific chat
   * @param {string} chatId - The chat ID
   * @param {number} limit - Maximum number of messages to retrieve (default: 50)
   * @param {number} offset - Offset for pagination (default: 0)
   * @returns {Promise<Object>} Chat history response with messages and total count
   */
  getChatById: async (chatId, limit = 50, offset = 0) => {
    try {
      const response = await axios.get(`/api/v1/history/chats/${chatId}?limit=${limit}&offset=${offset}`);
      return response.data;
    } catch (error) {
      console.error(`Error fetching chat ${chatId}:`, error);
      throw error;
    }
  },

  getInterviewReport: async (chatId, { partial = false } = {}) => {
    try {
      const suffix = partial ? '?partial=true' : '';
      const response = await axios.get(`/api/v1/history/chats/${chatId}/report${suffix}`);
      return response.data;
    } catch (error) {
      console.error(`Error fetching report for chat ${chatId}:`, error);
      throw error;
    }
  },

  downloadInterviewReportPdf: async (chatId) => {
    const response = await axios.get(`/api/v1/history/chats/${chatId}/report/pdf`, {
      responseType: 'blob',
    });
    return response.data;
  },

  retryEvaluation: async (chatId, pointId) => {
    const response = await axios.post(`/api/v1/history/chats/${chatId}/messages/${pointId}/evaluation/retry`);
    return response.data;
  },

  submitEvidenceFeedback: async (chatId, pointId, feedback) => {
    const response = await axios.post(
      `/api/v1/history/chats/${chatId}/messages/${pointId}/evaluation/evidence-feedback`,
      { feedback },
    );
    return response.data;
  },

  pauseInterview: async (chatId) => {
    const response = await axios.post(`/api/v1/history/chats/${chatId}/pause`);
    return response.data;
  },

  resumeInterview: async (chatId) => {
    const response = await axios.post(`/api/v1/history/chats/${chatId}/resume`);
    return response.data;
  },

  deleteInterview: async (chatId) => {
    const response = await axios.delete(`/api/v1/history/chats/${chatId}`);
    return response.data;
  },

  generateVoiceInterviewReport: async (payload) => {
    try {
      const response = await axios.post('/api/v1/history/voice/report', payload);
      return response.data;
    } catch (error) {
      console.error('Error generating voice interview report:', error);
      throw error;
    }
  },

  /**
   * Send a message to the chat API
   * @param {string} userMessage - The user's message
   * @param {string} chatId - The chat ID
   * @returns {Promise<Object>} The response data
   */
  sendMessage: async (userMessage, chatId, interviewConfig = {}) => {
    try {
      const response = await axios.post('/api/v1/chat/completions', {
        user_message: userMessage,
        chat_id: chatId,
        interview_role: interviewConfig.interviewRole,
        interview_level: interviewConfig.interviewLevel,
        interview_type: interviewConfig.interviewType,
        target_company: interviewConfig.targetCompany,
        jd_content: interviewConfig.jdContent,
        resume_content: interviewConfig.resumeContent,
      });
      return response.data;
    } catch (error) {
      console.error('Error sending message:', error);
      throw error;
    }
  },

  runCode: async ({ language, sourceCode, stdin = '', expectedOutput = '', onProgress }) => {
    try {
      const response = await axios.post('/api/v1/code/run', {
        language,
        source_code: sourceCode,
        stdin,
        expected_output: expectedOutput || null,
      });
      const { job_id: jobId } = response.data;
      const deadline = Date.now() + 90000;

      while (Date.now() < deadline) {
        const statusResponse = await axios.get(`/api/v1/code/run/${jobId}`);
        const job = statusResponse.data;
        onProgress?.(job.status);

        if (job.status === 'finished') {
          return job.result;
        }
        if (job.status === 'failed') {
          throw new Error(job.error || '代码执行任务失败，请稍后重试。');
        }

        await new Promise((resolve) => setTimeout(resolve, 500));
      }

      throw new Error('代码执行时间过长，请稍后查看或重新运行。');
    } catch (error) {
      console.error('Error running code:', error);
      throw error;
    }
  },
};

export default chatService;
