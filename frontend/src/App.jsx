import React, { useState, useEffect, useRef } from 'react'
import ChatInterface from './components/ChatInterface'
import { generateSessionId, getOrCreateUserId } from './utils/messageService'
import websocketService from './utils/websocketService'
import './App.css'

function App() {
  const [messages, setMessages] = useState([])
  const [isConnected, setIsConnected] = useState(false)
  const [isVoiceConnected, setIsVoiceConnected] = useState(false)
  const [isTyping, setIsTyping] = useState(false)
  const [isRecording, setIsRecording] = useState(false)
  const [isVoiceProcessing, setIsVoiceProcessing] = useState(false)
  const [sessionId, setSessionId] = useState(() => generateSessionId())
  const [userId] = useState(() => getOrCreateUserId())
  const [connectionError, setConnectionError] = useState(null)
  const streamingMessageRef = useRef(null)
  const messageIdCounter = useRef(0)
  const startFreshOnReconnectRef = useRef(false)
  const voiceWsRef = useRef(null)
  const voiceReconnectTimeoutRef = useRef(null)
  const voiceReconnectAttemptsRef = useRef(0)
  const mediaRecorderRef = useRef(null)
  const mediaStreamRef = useRef(null)
  const recordedChunksRef = useRef([])
  const audioContextRef = useRef(null)
  const queuedAudioBuffersRef = useRef([])
  const isAudioQueueRunningRef = useRef(false)
  const scheduledAudioTimeRef = useRef(0)
  const activeAudioSourcesRef = useRef(new Set())
  const backendHost = import.meta.env.VITE_BACKEND_HOST || '127.0.0.1:8000'
  const wsUrl = `ws://${backendHost}/ws/chat`
  const voiceWsUrl = `ws://${backendHost}/ws/voice_chat`
  
  // Generate unique message ID
  const generateMessageId = () => {
    messageIdCounter.current += 1
    return `msg_${Date.now()}_${messageIdCounter.current}`
  }

  const finalizeStreamingMessage = () => {
    setMessages(prev => {
      if (!streamingMessageRef.current) return prev
      const msgIndex = prev.findIndex(m => m.id === streamingMessageRef.current)
      if (msgIndex === -1) return prev
      return prev.map((msg, idx) => (
        idx === msgIndex ? { ...msg, streaming: false } : msg
      ))
    })
    streamingMessageRef.current = null
  }

  // Debug: Log every assistant token received from backend/model
  const pushAssistantToken = (token) => {
    if (!token) return
    console.log('[DEBUG] Assistant token received from backend/model:', token)
    setMessages(prev => {
      if (streamingMessageRef.current) {
        const msgIndex = prev.findIndex(m => m.id === streamingMessageRef.current)
        if (msgIndex !== -1) {
          const updatedMsg = { ...prev[msgIndex], content: prev[msgIndex].content + token }
          console.log('[DEBUG] Updated assistant message content (frontend state):', updatedMsg.content)
          return prev.map((msg, idx) => (
            idx === msgIndex ? updatedMsg : msg
          ))
        }
        streamingMessageRef.current = null
      }

      const newMsg = {
        role: 'assistant',
        content: token,
        timestamp: new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }),
        id: generateMessageId(),
        streaming: true
      }
      streamingMessageRef.current = newMsg.id
      console.log('[DEBUG] New assistant message created (frontend state):', newMsg.content)
      return [...prev, newMsg]
    })
  }

  const ensureAudioContext = async () => {
    const AudioCtx = window.AudioContext || window.webkitAudioContext
    if (!AudioCtx) {
      throw new Error('Web Audio API is not supported in this browser')
    }

    if (!audioContextRef.current) {
      audioContextRef.current = new AudioCtx()
    }

    if (audioContextRef.current.state === 'suspended') {
      await audioContextRef.current.resume()
    }

    return audioContextRef.current
  }

  const processQueuedAudio = async () => {
    if (isAudioQueueRunningRef.current) return
    isAudioQueueRunningRef.current = true

    try {
      while (queuedAudioBuffersRef.current.length > 0) {
        const nextArrayBuffer = queuedAudioBuffersRef.current.shift()
        if (!nextArrayBuffer) continue

        const audioContext = await ensureAudioContext()
        const decoded = await audioContext.decodeAudioData(nextArrayBuffer.slice(0))

        const source = audioContext.createBufferSource()
        source.buffer = decoded
        source.connect(audioContext.destination)

        const safeLeadTime = 0.02
        const startAt = Math.max(audioContext.currentTime + safeLeadTime, scheduledAudioTimeRef.current)
        source.start(startAt)
        scheduledAudioTimeRef.current = startAt + decoded.duration
        activeAudioSourcesRef.current.add(source)
        source.onended = () => {
          activeAudioSourcesRef.current.delete(source)
        }
      }
    } catch (error) {
      console.error('Seamless audio playback failed:', error)
    } finally {
      isAudioQueueRunningRef.current = false
    }
  }

  const enqueueAudioChunk = (base64Data) => {
    try {
      const binary = window.atob(base64Data)
      const bytes = new Uint8Array(binary.length)
      for (let i = 0; i < binary.length; i += 1) {
        bytes[i] = binary.charCodeAt(i)
      }

      queuedAudioBuffersRef.current.push(bytes.buffer)
      processQueuedAudio()
    } catch (error) {
      console.error('Failed to decode audio chunk:', error)
    }
  }

  const stopAndClearAudioPlayback = () => {
    for (const source of activeAudioSourcesRef.current) {
      try {
        source.stop()
      } catch (stopError) {
        // Ignore if already stopped.
      }
    }
    activeAudioSourcesRef.current.clear()
    queuedAudioBuffersRef.current = []
    scheduledAudioTimeRef.current = 0
    isAudioQueueRunningRef.current = false

    if (audioContextRef.current) {
      if (audioContextRef.current.state !== 'closed') {
        audioContextRef.current.close().catch(() => {})
      }
      audioContextRef.current = null
    }
  }

  const connectVoiceWebSocket = () => {
    if (voiceWsRef.current && voiceWsRef.current.readyState === WebSocket.OPEN) {
      return
    }

    const voiceWs = new WebSocket(voiceWsUrl)
    voiceWsRef.current = voiceWs

    voiceWs.onopen = () => {
      setIsVoiceConnected(true)
      voiceReconnectAttemptsRef.current = 0
      voiceWs.send(JSON.stringify({
        type: 'init',
        session_id: sessionId,
        user_id: userId
      }))
    }

    voiceWs.onclose = (event) => {
      setIsVoiceConnected(false)
      setIsTyping(false)
      setIsVoiceProcessing(false)
      finalizeStreamingMessage()

      // Auto-reconnect on backend restarts / network blips.
      if (event?.code !== 1000) {
        const attempt = voiceReconnectAttemptsRef.current + 1
        voiceReconnectAttemptsRef.current = attempt
        const delay = Math.min(15000, 1000 * attempt)
        if (voiceReconnectTimeoutRef.current) {
          clearTimeout(voiceReconnectTimeoutRef.current)
        }
        voiceReconnectTimeoutRef.current = setTimeout(() => {
          connectVoiceWebSocket()
        }, delay)
      }
    }

    voiceWs.onerror = () => {
      setIsVoiceConnected(false)
      setConnectionError('Voice WebSocket connection error')
    }

    voiceWs.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)

        if (data.type === 'transcript' && data.text) {
          const userMessage = {
            role: 'user',
            content: data.text,
            timestamp: new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }),
            id: generateMessageId()
          }
          setMessages(prev => [...prev, userMessage])
          setIsTyping(true)
          return
        }

        if (data.type === 'token') {
          pushAssistantToken(data.content || '')
          setIsTyping(true)
          return
        }

        if (data.type === 'audio_chunk' && data.audio) {
          setIsTyping(true)
          enqueueAudioChunk(data.audio)
          return
        }

        if (data.type === 'done') {
          finalizeStreamingMessage()
          setIsTyping(false)
          setIsVoiceProcessing(false)
          return
        }

        if (data.type === 'audio_done') {
          return
        }

        if (data.type === 'error') {
          setConnectionError(data.message || 'Voice pipeline error')
          setIsTyping(false)
          setIsVoiceProcessing(false)
        }
      } catch (error) {
        console.error('Unexpected voice message:', error)
      }
    }
  }

  // Initialize WebSocket connection
  useEffect(() => {
    console.log('Initializing WebSocket connection...')
    console.log('Session ID:', sessionId)
    console.log('User ID:', userId)
    
    // Set up WebSocket callbacks
    websocketService.onConnect(() => {
      console.log('WebSocket connected successfully')
      setIsConnected(true)
      setConnectionError(null)
      
      // Send initial handshake to register session with backend
      // Small delay to ensure WebSocket is fully ready (OPEN state)
      setTimeout(() => {
        const sent = websocketService.send({
          session_id: sessionId,
          message: "__INIT__", // Special init message that backend can ignore
          type: "init",
          user_id: userId
        })
        console.log('Init handshake sent:', sent)
      }, 100)
      
      // Add welcome message from assistant
      const welcomeMsg = {
        role: 'assistant',
        content: `Hello! I'm your Hotel Front Desk Assistant. How can I help you today?`,
        timestamp: new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }),
        id: generateMessageId()
      }
      if (startFreshOnReconnectRef.current) {
        // Backend restarted while frontend stayed open:
        // start a fresh visible chat window but keep same session/user IDs.
        setMessages([welcomeMsg])
        setIsTyping(false)
        setIsVoiceProcessing(false)
        streamingMessageRef.current = null
        stopAndClearAudioPlayback()
        startFreshOnReconnectRef.current = false
      } else {
        setMessages(prev => (prev && prev.length ? prev : [welcomeMsg]))
      }
    })
    
    websocketService.onDisconnect((event) => {
      console.log('WebSocket disconnected')
      setIsConnected(false)
      setIsTyping(false)
      finalizeStreamingMessage()
      
      // If backend drops connection (e.g., restart), open a fresh visible chat
      // after reconnect while keeping same session/user ids for CRM continuity.
      if (event.code !== 1000) {
        startFreshOnReconnectRef.current = true
        setConnectionError('Connection lost. Attempting to reconnect...')
      }
    })
    
    websocketService.onStreamToken((token) => {
      pushAssistantToken(token)
      setIsTyping(true)
    })
    
    websocketService.onMessage(({ type, data }) => {
      if (type === 'end') {
        finalizeStreamingMessage()
        setIsTyping(false)
      }
    })
    
    websocketService.onError((error) => {
      console.error('WebSocket error:', error)
      
      // Check if it's an Ollama connection error
      if (error.includes('Ollama') || error.includes('Could not connect')) {
        setConnectionError('⚠️ Ollama is not running. Please start Ollama and ensure the hotel-qwen model is loaded.')
      } else if (messages.length > 0) {
        // Only show error if we're not in initial connection state
        setConnectionError(error)
      }
      setIsTyping(false)
    })
    
    // Connect text and voice WebSockets (skip duplicate text connect in StrictMode).
    if (!websocketService.isConnected()) {
      console.log('Initiating WebSocket connection...')
      websocketService.connect(wsUrl)
    } else {
      console.log('WebSocket already connected, skipping connect()')
    }
    connectVoiceWebSocket()
    
    // Check connection status after a delay
    const connectionCheckTimeout = setTimeout(() => {
      if (!websocketService.isConnected()) {
        console.log('Starting in offline demo mode - backend not connected')
        setIsConnected(false)
        const welcomeMsg = {
          role: 'assistant',
          content: `Hello! I'm your Hotel Front Desk Assistant.\n\n⚠️ Backend server is not connected.\n\nTo start the backend:\n1. Open terminal\n2. cd backend\n3. python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload\n\nNote: Make sure Ollama is running with the hotel-qwen model loaded.`,
          timestamp: new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }),
          id: generateMessageId()
        }
        setMessages(prev => (prev && prev.length ? prev : [welcomeMsg]))
      }
    }, 3000) // Increased to 3 seconds to give more time
    
    // Cleanup on unmount
    return () => {
      console.log('Cleaning up WebSocket connection')
      clearTimeout(connectionCheckTimeout)
      websocketService.disconnect()
      if (voiceReconnectTimeoutRef.current) {
        clearTimeout(voiceReconnectTimeoutRef.current)
        voiceReconnectTimeoutRef.current = null
      }
      if (voiceWsRef.current) {
        voiceWsRef.current.close(1000, 'Client disconnecting')
        voiceWsRef.current = null
      }
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
        mediaRecorderRef.current.stop()
      }
      if (mediaStreamRef.current) {
        mediaStreamRef.current.getTracks().forEach(track => track.stop())
        mediaStreamRef.current = null
      }
      stopAndClearAudioPlayback()
    }
  }, [])

  useEffect(() => {
    if (voiceWsRef.current && voiceWsRef.current.readyState === WebSocket.OPEN) {
      voiceWsRef.current.send(JSON.stringify({ type: 'init', session_id: sessionId, user_id: userId }))
    }
  }, [sessionId])

  // WebSocket connection function (for manual reconnect)
  const connectWebSocket = () => {
    setConnectionError(null)
    websocketService.connect(wsUrl)
    connectVoiceWebSocket()
  }

  const handleSendMessage = (message) => {
    // Add user message to conversation history immediately
    const userMessage = {
      role: 'user',
      content: message,
      timestamp: new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }),
      id: generateMessageId()
    }
    
    setMessages(prev => [...prev, userMessage])
    
    // Prepare JSON payload with session_id and message
    const payload = {
      session_id: sessionId,
      message: message,
      user_id: userId
    }
    
    console.log('Sending message payload:', JSON.stringify(payload, null, 2))
    
    // Send message via WebSocket
    if (websocketService.isConnected()) {
      const success = websocketService.send(payload)
      
      if (success) {
        console.log('Message sent successfully via WebSocket')
        setIsTyping(true)
        streamingMessageRef.current = null // Reset for new message
      } else {
        console.error('Failed to send message via WebSocket')
        setConnectionError('Failed to send message')
      }
    } else {
      console.error('WebSocket is not connected')
      setConnectionError('Not connected to server. Please reconnect.')
    }
  }

  const handleResetSession = () => {
    // Confirm reset if there are messages (excluding welcome message)
    const hasConversation = messages.length > 1 || 
                           (messages.length === 1 && messages[0].role === 'user')
    
    if (hasConversation) {
      const confirmed = window.confirm(
        'Are you sure you want to start a new session? This will clear the current conversation.'
      )
      
      if (!confirmed) {
        return
      }
    }
    
    // Generate new session ID (no need to send reset - backend tracks per session)
    const newSessionId = generateSessionId()
    const oldSessionId = sessionId
    setSessionId(newSessionId)
    
    // Clear all messages and state
    setMessages([])
    setIsTyping(false)
    setIsRecording(false)
    setIsVoiceProcessing(false)
    setConnectionError(null)
    streamingMessageRef.current = null
    stopAndClearAudioPlayback()
    
    console.log('Session reset completed')
    console.log('Old session ID:', oldSessionId)
    console.log('New session ID:', newSessionId)
    
    // Add welcome message for new session
    setTimeout(() => {
      const welcomeMsg = {
        role: 'assistant',
        content: websocketService.isConnected() 
          ? `Hello! I'm your Hotel Front Desk Assistant. How can I help you today?`
          : `Hello! I'm your Hotel Front Desk Assistant.\n\n⚠️ Running in offline mode. Start the backend server to enable live chat.`,
        timestamp: new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }),
        id: generateMessageId()
      }
      setMessages([welcomeMsg])
    }, 100)
  }

  const handleStartRecording = async () => {
    if (!isVoiceConnected || isRecording || isVoiceProcessing) return

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      mediaStreamRef.current = stream

      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/webm'

      const recorder = new MediaRecorder(stream, { mimeType })
      mediaRecorderRef.current = recorder
      recordedChunksRef.current = []

      recorder.ondataavailable = (event) => {
        if (!event.data || event.data.size === 0) return
        // Keep chunks locally and send one complete container at stop.
        recordedChunksRef.current.push(event.data)
      }

      recorder.onstart = () => {
        if (voiceWsRef.current && voiceWsRef.current.readyState === WebSocket.OPEN) {
          voiceWsRef.current.send(JSON.stringify({
            type: 'audio_chunk_meta',
            session_id: sessionId,
            mime_type: mimeType
          }))
        }
        setIsRecording(true)
      }

      recorder.onstop = async () => {
        if (voiceWsRef.current && voiceWsRef.current.readyState === WebSocket.OPEN) {
          try {
            const fullBlob = new Blob(recordedChunksRef.current, { type: mimeType })
            const buffer = await fullBlob.arrayBuffer()
            voiceWsRef.current.send(buffer)
            voiceWsRef.current.send(JSON.stringify({
              type: 'audio_end',
              session_id: sessionId,
              mime_type: mimeType
            }))
          } catch (sendError) {
            console.error('Failed to send recorded audio:', sendError)
            setConnectionError('Failed to process recorded audio')
          }
        }

        recordedChunksRef.current = []

        if (mediaStreamRef.current) {
          mediaStreamRef.current.getTracks().forEach(track => track.stop())
          mediaStreamRef.current = null
        }

        setIsRecording(false)
        setIsVoiceProcessing(true)
      }

      // No timeslice so recorder emits one complete chunk on stop.
      recorder.start()
    } catch (error) {
      console.error('Microphone start failed:', error)
      setConnectionError('Microphone access failed. Please allow audio permission.')
      setIsRecording(false)
    }
  }

  const handleStopRecording = () => {
    if (!mediaRecorderRef.current || mediaRecorderRef.current.state === 'inactive') return
    mediaRecorderRef.current.stop()
  }

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-left">
          <button className="new-session-button" onClick={handleResetSession} title="Start new session">
            <svg stroke="currentColor" fill="none" strokeWidth="2" viewBox="0 0 24 24" strokeLinecap="round" strokeLinejoin="round" height="16" width="16" xmlns="http://www.w3.org/2000/svg">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
            </svg>
            <span className="hide-mobile">New Chat</span>
          </button>
        </div>
        
        <h1 className="app-title">Hotel Front Desk Assistant</h1>
        
        <div className="header-right">
          <div className="connection-status">
            <span className={`status-indicator ${isConnected && isVoiceConnected ? 'connected' : 'disconnected'}`}></span>
            <span className="hide-mobile">{isConnected && isVoiceConnected ? 'Connected' : 'Disconnected'}</span>
          </div>
        </div>
      </header>
      
      <ChatInterface
        messages={messages}
        onSendMessage={handleSendMessage}
        onResetSession={handleResetSession}
        onReconnect={connectWebSocket}
        isConnected={isConnected}
        isTyping={isTyping}
        sessionId={sessionId}
        connectionError={connectionError}
        isRecording={isRecording}
        isVoiceProcessing={isVoiceProcessing}
        isVoiceEnabled={isVoiceConnected}
        onStartRecording={handleStartRecording}
        onStopRecording={handleStopRecording}
      />
    </div>
  )
}

export default App
