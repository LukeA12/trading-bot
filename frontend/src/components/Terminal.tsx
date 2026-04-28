import { useEffect, useRef, useState, useCallback } from 'react'
import { Play, Pause, RefreshCw } from 'lucide-react'

interface LogEntry {
  timestamp: string
  type: 'info' | 'success' | 'warning' | 'error' | 'data' | 'trade' | 'heartbeat'
  message: string
  data?: Record<string, any>
}

interface Props {
  isRunning: boolean
  lastRun: string | null
  stats: {
    total_trades: number
    total_pnl: number
  }
  onStart?: () => void
  onStop?: () => void
  onScan?: () => void
}

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const WS_URL = API_URL.replace(/^http/, 'ws') + '/ws/events'

export function Terminal({ isRunning, lastRun, onStart, onStop, onScan }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [cursorVisible, setCursorVisible] = useState(true)
  const [wsConnected, setWsConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Fetch initial events
  const fetchEvents = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/events?limit=30`)
      if (res.ok) {
        const events = await res.json()
        setLogs(events.filter((e: LogEntry) => e.type !== 'heartbeat'))
      }
    } catch (err) {
      console.error('Failed to fetch events:', err)
    }
  }, [])

  // WebSocket connection
  useEffect(() => {
    const connectWs = () => {
      try {
        const ws = new WebSocket(WS_URL)
        wsRef.current = ws

        ws.onopen = () => {
          setWsConnected(true)
          setLogs(prev => [...prev, {
            timestamp: new Date().toISOString(),
            type: 'success',
            message: 'WebSocket connected'
          }])
        }

        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data)
            if (data.type === 'heartbeat') return // Skip heartbeats
            setLogs(prev => [...prev.slice(-100), data])
          } catch (e) {
            console.error('Failed to parse WebSocket message:', e)
          }
        }

        ws.onclose = () => {
          setWsConnected(false)
          wsRef.current = null
          // Attempt reconnect after 5 seconds
          reconnectTimeoutRef.current = setTimeout(connectWs, 5000)
        }

        ws.onerror = () => {
          ws.close()
        }
      } catch (err) {
        // Fallback to polling if WebSocket fails
        setWsConnected(false)
      }
    }

    // Initial fetch and connect
    fetchEvents()
    connectWs()

    return () => {
      if (wsRef.current) {
        wsRef.current.close()
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
      }
    }
  }, [fetchEvents])

  // Polling fallback if WebSocket not connected
  useEffect(() => {
    if (wsConnected) return

    const interval = setInterval(fetchEvents, 5000)
    return () => clearInterval(interval)
  }, [wsConnected, fetchEvents])

  // Auto-scroll to bottom
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [logs])

  // Cursor blink
  useEffect(() => {
    const interval = setInterval(() => {
      setCursorVisible(v => !v)
    }, 500)
    return () => clearInterval(interval)
  }, [])

  const formatTime = (timestamp: string) => {
    try {
      return new Date(timestamp).toLocaleTimeString('en-US', { hour12: false })
    } catch {
      return '--:--:--'
    }
  }

  const getTypeColor = (type: LogEntry['type']) => {
    switch (type) {
      case 'success': return 'text-emerald-400'
      case 'error': return 'text-rose-400'
      case 'warning': return 'text-amber-400'
      case 'data': return 'text-indigo-400'
      case 'trade': return 'text-violet-400'
      default: return 'text-slate-400'
    }
  }

  const getTypePrefix = (type: LogEntry['type']) => {
    switch (type) {
      case 'success': return '[OK]'
      case 'error': return '[ERR]'
      case 'warning': return '[WARN]'
      case 'data': return '[DATA]'
      case 'trade': return '[TRADE]'
      default: return '[INFO]'
    }
  }

  return (
    <div className="terminal h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-indigo-500/10">
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-400 font-medium">System Log</span>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <div className={`w-1.5 h-1.5 rounded-full ${wsConnected ? 'bg-emerald-400 shadow-[0_0_4px_rgba(52,211,153,0.4)]' : 'bg-amber-400'}`} />
            <span className="text-[11px] text-slate-500 font-light">
              {wsConnected ? 'WS' : 'Poll'}
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            {isRunning && <div className="live-dot" />}
            <span className="text-[11px] text-slate-500 font-light">
              {isRunning ? 'Live' : 'Idle'}
            </span>
          </div>
        </div>
      </div>

      {/* Log content */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-3 space-y-0.5 min-h-0">
        {logs.length === 0 ? (
          <div className="text-slate-500 text-xs font-light">Waiting for events...</div>
        ) : (
          logs.map((log, i) => (
            <div key={i} className="flex gap-2 text-xs leading-relaxed">
              <span className="text-slate-600 tabular-nums shrink-0" style={{ fontFamily: 'IBM Plex Mono, monospace' }}>
                {formatTime(log.timestamp)}
              </span>
              <span className={`shrink-0 ${getTypeColor(log.type)}`} style={{ fontFamily: 'IBM Plex Mono, monospace' }}>
                {getTypePrefix(log.type)}
              </span>
              <span className={getTypeColor(log.type)}>
                {log.message}
              </span>
            </div>
          ))
        )}

        {/* Cursor line */}
        <div className="flex gap-2 text-xs">
          <span className="text-slate-600 tabular-nums" style={{ fontFamily: 'IBM Plex Mono, monospace' }}>
            {formatTime(new Date().toISOString())}
          </span>
          <span className="text-indigo-400">{'>'}</span>
          <span className={`text-indigo-400 ${cursorVisible ? 'opacity-100' : 'opacity-0'}`}>_</span>
        </div>
      </div>

      {/* Footer with controls */}
      <div className="px-3 py-1.5 border-t border-indigo-500/10 flex justify-between items-center">
        <div className="flex items-center gap-2">
          {onStart && onStop && (
            <button
              onClick={isRunning ? onStop : onStart}
              className={`flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-medium rounded-md border transition-all ${
                isRunning
                  ? 'border-amber-400/20 text-amber-400 hover:bg-amber-400/10'
                  : 'border-emerald-400/20 text-emerald-400 hover:bg-emerald-400/10'
              }`}
            >
              {isRunning ? <Pause className="w-3 h-3" /> : <Play className="w-3 h-3" />}
              {isRunning ? 'Pause' : 'Start'}
            </button>
          )}
          {onScan && (
            <button
              onClick={onScan}
              className="flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-medium rounded-md border border-indigo-400/20 text-indigo-400 hover:bg-indigo-400/10 transition-all"
            >
              <RefreshCw className="w-3 h-3" />
              Scan
            </button>
          )}
        </div>
        <div className="flex items-center gap-4">
          <span className="text-[11px] text-slate-500 font-light">
            {lastRun ? `Last: ${formatTime(lastRun)}` : 'No scans'}
          </span>
          <span className="text-[11px] text-slate-500 tabular-nums font-light">
            {logs.length} entries
          </span>
        </div>
      </div>
    </div>
  )
}
