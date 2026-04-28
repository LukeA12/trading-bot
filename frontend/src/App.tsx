import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { fetchDashboard, runScan, startBot, stopBot } from './api'
import { StatsCards } from './components/StatsCards'
import { TradesTable } from './components/TradesTable'
import { EquityChart } from './components/EquityChart'
import { Terminal } from './components/Terminal'
import { CalibrationPanel } from './components/CalibrationPanel'
import { WeatherPanel } from './components/WeatherPanel'

function LiveClock() {
  const [time, setTime] = useState(new Date())
  useEffect(() => {
    const interval = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(interval)
  }, [])
  return (
    <span className="text-xs tabular-nums text-neutral-400">
      {time.toLocaleTimeString('en-US', { hour12: false })}
    </span>
  )
}

function RefreshBar({ interval }: { interval: number }) {
  const [progress, setProgress] = useState(100)

  useEffect(() => {
    setProgress(100)
    const step = 100 / (interval / 1000)
    const timer = setInterval(() => {
      setProgress(p => Math.max(0, p - step))
    }, 1000)
    return () => clearInterval(timer)
  }, [interval])

  return (
    <div className="refresh-bar w-16">
      <div className="refresh-fill" style={{ width: `${progress}%` }} />
    </div>
  )
}

function App() {
  const queryClient = useQueryClient()

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['dashboard'],
    queryFn: fetchDashboard,
    refetchInterval: 10000,
  })

  const scanMutation = useMutation({
    mutationFn: runScan,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
  })

  const startMutation = useMutation({
    mutationFn: startBot,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
  })

  const stopMutation = useMutation({
    mutationFn: stopBot,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
  })

  const recentTrades = data?.recent_trades ?? []
  const weatherSignals = data?.weather_signals ?? []
  const weatherForecasts = data?.weather_forecasts ?? []

  const stats = data?.stats ?? {
    is_running: false,
    last_run: null,
    total_trades: 0,
    total_pnl: 0,
    bankroll: 10000,
    winning_trades: 0,
    win_rate: 0
  }
  const equityCurve = data?.equity_curve ?? []
  const calibration = data?.calibration ?? null

  if (isLoading) {
    return (
      <div className="h-screen bg-black flex items-center justify-center">
        <div className="text-center">
          <div className="relative w-10 h-10 mx-auto mb-4">
            <div className="absolute inset-0 border-2 border-neutral-800 rounded-full" />
            <div className="absolute inset-0 border-2 border-transparent border-t-green-500 rounded-full animate-spin" />
          </div>
          <div className="text-[10px] text-neutral-500 uppercase tracking-widest font-mono">Initializing</div>
        </div>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="h-screen bg-black flex items-center justify-center">
        <div className="text-center">
          <div className="text-red-500 text-xs uppercase mb-2 tracking-wider">Connection Error</div>
          <button
            onClick={() => refetch()}
            className="px-3 py-1.5 bg-neutral-900 border border-neutral-700 text-neutral-300 text-xs uppercase tracking-wider"
          >
            Retry
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="h-screen bg-black text-neutral-200 flex flex-col overflow-hidden">
      {/* ===== HEADER ===== */}
      <motion.header
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="shrink-0 border-b border-neutral-800 px-3 py-1.5 flex items-center gap-4 relative"
      >
        <div className="scan-line" />

        <div className="flex items-center gap-2 shrink-0">
          <h1 className="text-xs font-bold text-neutral-100 uppercase tracking-widest whitespace-nowrap font-mono">
            WEATHER TRADING TERMINAL
          </h1>
          <span className={`px-1.5 py-0.5 text-[9px] font-bold uppercase ${
            stats.is_running
              ? 'bg-green-500/10 text-green-500 border border-green-500/20'
              : 'bg-neutral-800 text-neutral-500 border border-neutral-700'
          }`}>
            {stats.is_running ? 'Live' : 'Idle'}
          </span>
          <span className="px-1.5 py-0.5 text-[9px] font-bold uppercase bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
            WX
          </span>
        </div>

        <div className="flex-1" />

        <StatsCards stats={stats} />

        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={() => scanMutation.mutate()}
            disabled={scanMutation.isPending}
            className="px-2.5 py-1 bg-neutral-900 border border-neutral-700 hover:border-neutral-600 text-neutral-300 text-[10px] uppercase tracking-wider transition-colors disabled:opacity-50 whitespace-nowrap"
          >
            {scanMutation.isPending ? 'Scanning...' : 'Scan'}
          </button>
          <LiveClock />
        </div>
      </motion.header>

      {/* ===== MAIN GRID ===== */}
      <div className="flex-1 min-h-0 grid grid-cols-[1fr_340px] grid-rows-[1fr] gap-0">

        {/* ===== LEFT / CENTER AREA ===== */}
        <div className="flex flex-col min-h-0 border-r border-neutral-800">

          {/* TOP: Equity Chart (largest view) */}
          <div className="border-b border-neutral-800" style={{ height: '45%', minHeight: '200px' }}>
            <div className="px-3 py-1.5 border-b border-neutral-800 flex items-center justify-between shrink-0">
              <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Equity Curve</span>
              <div className="flex items-center gap-3">
                <span className={`text-sm font-semibold tabular-nums ${stats.total_pnl >= 0 ? 'text-green-500 glow-green' : 'text-red-500 glow-red'}`}>
                  {stats.total_pnl >= 0 ? '+' : ''}${stats.total_pnl.toFixed(2)}
                </span>
                <span className="text-[10px] text-neutral-600">
                  Bank: ${stats.bankroll >= 1000 ? (stats.bankroll / 1000).toFixed(1) + 'K' : stats.bankroll.toFixed(0)}
                </span>
              </div>
            </div>
            <div className="h-[calc(100%-32px)] p-2">
              <EquityChart data={equityCurve} initialBankroll={stats.bankroll - stats.total_pnl} />
            </div>
          </div>

          {/* BOTTOM: 3 panels side by side */}
          <div className="flex-1 min-h-0 grid grid-cols-3 gap-0">

            {/* Weather Forecasts */}
            <div className="border-r border-neutral-800 flex flex-col min-h-0">
              <div className="px-2 py-1 border-b border-neutral-800 flex items-center justify-between shrink-0">
                <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Weather Forecasts</span>
                <span className="px-1 py-0.5 text-[8px] font-bold uppercase bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">WX</span>
              </div>
              <div className="flex-1 min-h-0 overflow-y-auto">
                <WeatherPanel forecasts={weatherForecasts} signals={weatherSignals} />
              </div>
            </div>

            {/* System Log */}
            <div className="border-r border-neutral-800 flex flex-col min-h-0">
              <Terminal
                isRunning={stats.is_running}
                lastRun={stats.last_run}
                stats={{ total_trades: stats.total_trades, total_pnl: stats.total_pnl }}
                onStart={() => startMutation.mutate()}
                onStop={() => stopMutation.mutate()}
                onScan={() => scanMutation.mutate()}
              />
            </div>

            {/* Calibration */}
            <div className="flex flex-col min-h-0">
              <div className="px-2 py-1 border-b border-neutral-800 shrink-0">
                <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Calibration</span>
              </div>
              <div className="flex-1 min-h-0 overflow-y-auto p-2">
                {calibration && calibration.total_with_outcome > 0 ? (
                  <CalibrationPanel calibration={calibration} />
                ) : (
                  <div className="h-full flex items-center justify-center text-neutral-600 text-[10px]">
                    No calibration data yet
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* ===== RIGHT COLUMN: Trades (full height) ===== */}
        <div className="flex flex-col min-h-0 overflow-hidden">
          <div className="px-2 py-1 border-b border-neutral-800 flex items-center justify-between shrink-0">
            <span className="text-[10px] text-neutral-500 uppercase tracking-wider">Trades</span>
            <span className="text-[10px] text-neutral-600 tabular-nums">{recentTrades.length}</span>
          </div>
          <div className="flex-1 overflow-y-auto min-h-0">
            <TradesTable trades={recentTrades} />
          </div>
        </div>
      </div>

      {/* ===== FOOTER ===== */}
      <footer className="shrink-0 border-t border-neutral-800 px-3 py-0.5 flex items-center justify-between">
        <span className="text-[10px] text-neutral-700 font-mono">
          Open-Meteo | Polymarket + Kalshi
        </span>
        <div className="flex items-center gap-3">
          <RefreshBar interval={10000} />
          <span className="text-[10px] text-neutral-700 font-mono">Weather Temp Markets</span>
          <div className="flex items-center gap-1">
            <div className="w-1.5 h-1.5 rounded-full bg-green-500" />
            <span className="text-[10px] text-neutral-600 font-mono">Connected</span>
          </div>
        </div>
      </footer>
    </div>
  )
}

export default App
