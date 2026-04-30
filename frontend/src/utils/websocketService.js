/**
 * WebSocket Service - Handles WebSocket connection and streaming
 */

class WebSocketService {
  constructor() {
    this.ws = null
    this.lastUrl = null
    this.reconnectAttempts = 0
    this.maxReconnectAttempts = 5
    this.reconnectDelay = 2000
    this.reconnectTimeout = null
    this.onMessageCallback = null
    this.onConnectCallback = null
    this.onDisconnectCallback = null
    this.onErrorCallback = null
    this.onStreamTokenCallback = null
    this.shouldReconnect = true
  }

  /**
   * Connect to WebSocket server
   * @param {string} url - WebSocket URL (e.g., 'ws://localhost:8000/ws/chat')
   */
  connect(url) {
    // Enable reconnection attempts
    this.shouldReconnect = true
    this.lastUrl = url || this.lastUrl
    
    try {
      console.log('Connecting to WebSocket:', url)
      this.ws = new WebSocket(url)
      
      this.ws.onopen = this.handleOpen.bind(this)
      this.ws.onmessage = this.handleMessage.bind(this)
      this.ws.onclose = this.handleClose.bind(this)
      this.ws.onerror = this.handleError.bind(this)
    } catch (error) {
      console.error('Failed to create WebSocket connection:', error)
      this.handleError(error)
    }
  }

  /**
   * Handle WebSocket open event
   */
  handleOpen(event) {
    // Safety check: ensure ws still exists (may be null if disconnect was called)
    if (!this.ws) {
      console.warn('WebSocket opened but this.ws is null (likely disconnected during connection)')
      return
    }
    
    console.log('WebSocket opened, readyState:', this.ws.readyState)
    console.log('WebSocket OPEN constant:', WebSocket.OPEN)
    this.reconnectAttempts = 0
    
    if (this.onConnectCallback) {
      this.onConnectCallback()
    }
  }

  /**
   * Handle incoming WebSocket messages
   */
  handleMessage(event) {
    try {
      // Try to parse as JSON first
      const data = JSON.parse(event.data)
      console.log('WebSocket message received:', data)
      
      // Handle different message types
      if (data.type === 'token') {
        // Streaming token from assistant
        if (this.onStreamTokenCallback) {
          this.onStreamTokenCallback(data.content)
        }
      } else if (data.type === 'done' || data.type === 'end') {
        // End of streaming
        if (this.onMessageCallback) {
          this.onMessageCallback({ type: 'end', data })
        }
      } else if (data.type === 'error') {
        // Error from backend
        console.error('Backend error:', data.message)
        if (this.onErrorCallback) {
          this.onErrorCallback(data.message)
        }
      } else if (data.type === 'status') {
        // Status message (e.g., "Processing your request...")
        console.log('Status:', data.message)
      } else {
        // Full message or other types
        if (this.onMessageCallback) {
          this.onMessageCallback({ type: 'message', data })
        }
      }
    } catch (error) {
      // If not JSON, treat as raw token for streaming (backend sends raw text tokens)
      if (this.onStreamTokenCallback) {
        this.onStreamTokenCallback(event.data)
      }
    }
  }

  /**
   * Handle WebSocket close event
   */
  handleClose(event) {
    console.log('WebSocket closed!')
    console.log('  - Code:', event.code, '(1000=Normal, 1006=Abnormal)')
    console.log('  - Reason:', event.reason || '(no reason provided)')
    console.log('  - Clean:', event.wasClean)
    this.ws = null
    
    if (this.onDisconnectCallback) {
      this.onDisconnectCallback(event)
    }
    
    // Attempt to reconnect if not intentionally closed and haven't exceeded max attempts
    if (this.shouldReconnect && event.code !== 1000 && this.reconnectAttempts < this.maxReconnectAttempts) {
      this.reconnectAttempts++
      const delay = this.reconnectDelay * this.reconnectAttempts
      console.log(`Attempting to reconnect in ${delay}ms (${this.reconnectAttempts}/${this.maxReconnectAttempts})...`)
      
      this.reconnectTimeout = setTimeout(() => {
        const url = this.lastUrl || 'ws://localhost:8000/ws/chat'
        this.connect(url)
      }, delay)
    } else if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error('Max reconnection attempts reached')
      if (this.onErrorCallback) {
        this.onErrorCallback('Failed to reconnect after multiple attempts. Please check if the backend server is running.')
      }
    }
  }

  /**
   * Handle WebSocket error
   */
  handleError(error) {
    console.error('WebSocket error:', error)
    
    if (this.onErrorCallback) {
      this.onErrorCallback('WebSocket connection error')
    }
  }

  /**
   * Send message through WebSocket
   * @param {object} payload - Message payload with session_id and message
   */
  send(payload) {
    if (!this.ws) {
      console.error('WebSocket is null')
      return false
    }
    
    if (this.ws.readyState !== WebSocket.OPEN) {
      console.error('WebSocket is not OPEN. Current state:', this.ws.readyState, 
        '(0=CONNECTING, 1=OPEN, 2=CLOSING, 3=CLOSED)')
      return false
    }

    try {
      const jsonPayload = JSON.stringify(payload)
      console.log('Sending WebSocket message:', jsonPayload)
      this.ws.send(jsonPayload)
      console.log('Message sent successfully')
      return true
    } catch (error) {
      console.error('Error sending WebSocket message:', error)
      return false
    }
  }

  /**
   * Send reset/clear session signal to backend
   * @param {string} sessionId - Session ID to reset
   */
  sendReset(sessionId) {
    const payload = {
      type: 'reset',
      session_id: sessionId
    }
    return this.send(payload)
  }

  /**
   * Close WebSocket connection
   */
  disconnect() {
    this.shouldReconnect = false
    
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout)
      this.reconnectTimeout = null
    }
    
    if (this.ws) {
      // Remove event handlers to prevent race conditions
      this.ws.onopen = null
      this.ws.onmessage = null
      this.ws.onclose = null
      this.ws.onerror = null
      
      // Only close if not already closed
      if (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING) {
        this.ws.close(1000, 'Client disconnecting')
      }
      
      this.ws = null
    }
    
    console.log('WebSocket disconnected')
  }

  /**
   * Check if WebSocket is connected
   */
  isConnected() {
    return this.ws && this.ws.readyState === WebSocket.OPEN
  }

  /**
   * Set callback for connection established
   */
  onConnect(callback) {
    this.onConnectCallback = callback
  }

  /**
   * Set callback for disconnection
   */
  onDisconnect(callback) {
    this.onDisconnectCallback = callback
  }

  /**
   * Set callback for full messages
   */
  onMessage(callback) {
    this.onMessageCallback = callback
  }

  /**
   * Set callback for streaming tokens
   */
  onStreamToken(callback) {
    this.onStreamTokenCallback = callback
  }

  /**
   * Set callback for errors
   */
  onError(callback) {
    this.onErrorCallback = callback
  }
}

// Export singleton instance
export default new WebSocketService()
