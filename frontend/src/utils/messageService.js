/**
 * Message Service - Handles message formatting and sending
 */

/**
 * Generate a unique session ID
 * @returns {string} session ID
 */
export const generateSessionId = () => {
  return `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
}

/**
 * Generate a new user id for each session (no persistence).
 * Each page load/new session gets a fresh user_id to ensure data isolation.
 * This prevents data from previous sessions from bleeding into new sessions.
 */
export const getOrCreateUserId = () => {
  // Generate a new user_id for each session - don't persist in localStorage
  return `user_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
}

/**
 * Create a message payload for sending to backend
 * @param {string} sessionId - Current session ID
 * @param {string} message - User message text
 * @returns {object} Message payload
 */
export const createMessagePayload = (sessionId, message) => {
  return {
    session_id: sessionId,
    message: message
  }
}

/**
 * Send message via WebSocket
 * @param {WebSocket} ws - WebSocket connection
 * @param {string} sessionId - Current session ID
 * @param {string} message - User message text
 * @returns {boolean} Success status
 */
export const sendMessage = (ws, sessionId, message) => {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    console.error('WebSocket is not connected')
    return false
  }

  try {
    const payload = createMessagePayload(sessionId, message)
    const jsonPayload = JSON.stringify(payload)
    
    console.log('Sending message:', jsonPayload)
    ws.send(jsonPayload)
    return true
  } catch (error) {
    console.error('Error sending message:', error)
    return false
  }
}

/**
 * Send message via HTTP POST (fallback)
 * @param {string} sessionId - Current session ID
 * @param {string} message - User message text
 * @returns {Promise<object>} Response data
 */
export const sendMessageHTTP = async (sessionId, message) => {
  const payload = createMessagePayload(sessionId, message)
  
  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload)
    })
    
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`)
    }
    
    return await response.json()
  } catch (error) {
    console.error('Error sending message via HTTP:', error)
    throw error
  }
}
