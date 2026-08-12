/**
 * Service for handling streaming responses from the chat API
 */
const streamingService = {
  /**
   * Start a streaming request to the chat completions API
   * @param {string} userMessage - The user message to send
   * @param {string} chatId - The chat ID
   * @param {Object} callbacks - Callback functions for handling the stream
   * @param {Function} callbacks.onChunk - Called when a chunk is received
   * @param {Function} callbacks.onComplete - Called when the stream is complete
   * @param {Function} callbacks.onError - Called when an error occurs
   * @returns {Object} - Controller object with abort method
   */
  startStream: (userMessage, chatId, callbacks, interviewConfig = {}) => {
    const controller = new AbortController();
    const { signal } = controller;

    const body = JSON.stringify({
      user_message: userMessage,
      chat_id: chatId,
      interview_role: interviewConfig.interviewRole,
      interview_level: interviewConfig.interviewLevel,
      interview_type: interviewConfig.interviewType,
      target_company: interviewConfig.targetCompany,
      jd_content: interviewConfig.jdContent,
      resume_content: interviewConfig.resumeContent,
      code_execution: interviewConfig.codeExecution || null,
    });

    const token = localStorage.getItem('token');

    console.log(`Starting stream for chat ${chatId} with message: ${userMessage.substring(0, 20)}...`);

    let accumulatedContent = '';

    try {
      callbacks.onChunk('');
      
      console.log('Sending request to streaming endpoint...');

      fetch('/api/v1/chat/completions', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body,
        signal
      })
      .then(async response => {
        if (!response.ok) {
          let detail = `HTTP error! Status: ${response.status}`;
          try {
            const payload = await response.json();
            detail = payload?.detail || detail;
          } catch (e) {
            console.error('Failed to parse error response:', e);
          }
          throw new Error(detail);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';
        let completed = false;

        const processEvent = (event) => {
          const dataLines = event
            .replace(/\r\n/g, '\n')
            .split('\n')
            .filter((line) => line.startsWith('data:'))
            .map((line) => line.slice(5).replace(/^ /, ''));
          if (!dataLines.length) return;

          const data = dataLines.join('\n');
          if (data === '[DONE]') {
            console.log('Received [DONE] message');
            return;
          }

          try {
            const parsedData = JSON.parse(data);
            const delta = parsedData?.choices?.[0]?.delta;
            if (delta?.content) {
              accumulatedContent += delta.content;
              callbacks.onChunk(delta.content);
            }
            if (parsedData?.choices?.[0]?.finish_reason) {
              console.log('Finish reason:', parsedData.choices[0].finish_reason);
            }
          } catch (error) {
            console.error('Error parsing SSE JSON:', error, data);
          }
        };

        const processBuffer = (flush = false) => {
          buffer = buffer.replace(/\r\n/g, '\n');
          const events = buffer.split('\n\n');
          buffer = events.pop() || '';
          events.forEach(processEvent);
          if (flush && buffer.trim()) {
            processEvent(buffer.trim());
            buffer = '';
          }
        };

        const complete = () => {
          if (completed) return;
          completed = true;
          buffer += decoder.decode();
          processBuffer(true);
          console.log('Stream complete, final content:', accumulatedContent);
          callbacks.onComplete();
        };

        const readStream = async () => {
          while (true) {
            const { done, value } = await reader.read();
            if (done) {
              complete();
              return;
            }
            buffer += decoder.decode(value, { stream: true });
            processBuffer(false);
          }
        };

        return readStream();
      })
      .catch(error => {
        if (error.name === 'AbortError') {
          console.log('Stream aborted');
        } else {
          console.error('Streaming error:', error);
          callbacks.onError(error);
        }
      });
    } catch (error) {
      console.error('Error setting up stream:', error);
      callbacks.onError(error);
    }

    return {
      abort: () => controller.abort()
    };
  }
};

export default streamingService;
