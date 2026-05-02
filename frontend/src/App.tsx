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
    <span className="text-xs tabular-nums text-slate-400 font-light">
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
  const equityByStrategy = data?.equity_by_strategy ?? {}
  const calibration = data?.calibration ?? null

  if (isLoading) {
    return (
      <div className="h-screen bg-[#0c1222] flex items-center justify-center">
        <div className="text-center">
          <div className="relative w-12 h-12 mx-auto mb-4">
            <div className="absolute inset-0 border-2 border-indigo-500/10 rounded-full" />
            <div className="absolute inset-0 border-2 border-transparent border-t-indigo-400 rounded-full animate-spin" />
          </div>
          <div className="text-xs text-slate-500 tracking-wide font-light">Loading dashboard...</div>
        </div>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="h-screen bg-[#0c1222] flex items-center justify-center">
        <div className="text-center">
          <div className="text-rose-400 text-sm mb-3 font-medium">Connection Error</div>
          <button
            onClick={() => refetch()}
            className="px-4 py-2 bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 text-xs rounded-lg hover:bg-indigo-500/20 transition-all"
          >
            Retry Connection
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="h-screen bg-[#0c1222] text-slate-200 flex flex-col overflow-hidden">
      {/* ===== HEADER ===== */}
      <motion.header
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="shrink-0 border-b border-indigo-500/10 px-4 py-2 flex items-center gap-4 relative bg-[#0c1222]/80 backdrop-blur-xl"
      >
        <div className="scan-line" />

        <div className="flex items-center gap-3 shrink-0">
          <h1 className="text-sm font-semibold text-slate-100 whitespace-nowrap tracking-tight">
            Weather Trading
          </h1>
          <span className={`px-2 py-0.5 text-[10px] font-medium rounded-full ${
            stats.is_running
              ? 'bg-emerald-400/10 text-emerald-400 border border-emerald-400/20'
              : 'bg-slate-700/30 text-slate-400 border border-slate-600/20'
          }`}>
            {stats.is_running ? 'Live' : 'Idle'}
          </span>
          <span className="px-2 py-0.5 text-[10px] font-medium rounded-full bg-violet-400/10 text-violet-400 border border-violet-400/20">
            Weather
          </span>
        </div>

        <div className="flex-1" />

        <StatsCards stats={stats} />

        <div className="flex items-center gap-3 shrink-0">
          <button
            onClick={() => scanMutation.mutate()}
            disabled={scanMutation.isPending}
            className="px-3 py-1.5 bg-indigo-500/10 border border-indigo-500/20 hover:bg-indigo-500/20 text-indigo-300 text-[11px] font-medium rounded-lg transition-all disabled:opacity-50 whitespace-nowrap"
          >
            {scanMutation.isPending ? 'Scanning...' : 'Run Scan'}
          </button>
          <LiveClock />
        </div>
      </motion.header>

      {/* ===== MAIN GRID ===== */}
      <div className="flex-1 min-h-0 grid grid-cols-[1fr_340px] grid-rows-[1fr] gap-0">

        {/* ===== LEFT / CENTER AREA ===== */}
        <div className="flex flex-col min-h-0 border-r border-indigo-500/10">

          {/* TOP: Equity Chart (largest view) */}
          <div className="border-b border-indigo-500/10" style={{ height: '45%', minHeight: '200px' }}>
            <div className="px-4 py-2 border-b border-indigo-500/10 flex items-center justify-between shrink-0">
              <span className="text-xs text-slate-400 font-medium">Equity Curve</span>
              <div className="flex items-center gap-3">
                <span className={`text-sm font-semibold tabular-nums ${stats.total_pnl >= 0 ? 'text-emerald-400 glow-green' : 'text-rose-400 glow-red'}`}>
                  {stats.total_pnl >= 0 ? '+' : ''}${stats.total_pnl.toFixed(2)}
                </span>
                <span className="text-[11px] text-slate-500 font-light">
                  Bank: ${stats.bankroll >= 1000 ? (stats.bankroll / 1000).toFixed(1) + 'K' : stats.bankroll.toFixed(0)}
                </span>
              </div>
            </div>
            <div className="h-[calc(100%-36px)] p-3">
              <EquityChart data={equityCurve} initialBankroll={stats.bankroll - stats.total_pnl} equityByStrategy={equityByStrategy} />
            </div>
          </div>

          {/* BOTTOM: 3 panels side by side */}
          <div className="flex-1 min-h-0 grid grid-cols-3 gap-0">

            {/* Weather Forecasts */}
            <div className="border-r border-indigo-500/10 flex flex-col min-h-0">
              <div className="px-3 py-1.5 border-b border-indigo-500/10 flex items-center justify-between shrink-0">
                <span className="text-xs text-slate-400 font-medium">Weather Forecasts</span>
                <span className="px-1.5 py-0.5 text-[9px] font-medium rounded-full bg-violet-400/10 text-violet-400 border border-violet-400/20">WX</span>
              </div>
              <div className="flex-1 min-h-0 overflow-y-auto">
                <WeatherPanel forecasts={weatherForecasts} signals={weatherSignals} />
              </div>
            </div>

            {/* System Log */}
            <div className="border-r border-indigo-500/10 flex flex-col min-h-0">
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
              <div className="px-3 py-1.5 border-b border-indigo-500/10 shrink-0">
                <span className="text-xs text-slate-400 font-medium">Calibration</span>
              </div>
              <div className="flex-1 min-h-0 overflow-y-auto p-3">
                {calibration && calibration.total_with_outcome > 0 ? (
                  <CalibrationPanel calibration={calibration} />
                ) : (
                  <div className="h-full flex items-center justify-center text-slate-500 text-xs">
                    No calibration data yet
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* ===== RIGHT COLUMN: Trades (full height) ===== */}
        <div className="flex flex-col min-h-0 overflow-hidden">
          <div className="px-3 py-1.5 border-b border-indigo-500/10 flex items-center justify-between shrink-0">
            <span className="text-xs text-slate-400 font-medium">Trades</span>
            <span className="text-[11px] text-slate-500 tabular-nums font-light">{recentTrades.length}</span>
          </div>
          <div className="flex-1 overflow-y-auto min-h-0">
            <TradesTable trades={recentTrades} />
          </div>
        </div>
      </div>

      {/* ===== FOOTER ===== */}
      <footer className="shrink-0 border-t border-indigo-500/10 px-4 py-1 flex items-center justify-between bg-[#0c1222]/80 backdrop-blur-xl">
        <span className="text-[11px] text-slate-600 font-light">
          Open-Meteo · Polymarket · Kalshi
        </span>
        <div className="flex items-center gap-4">
          <RefreshBar interval={10000} />
          <span className="text-[11px] text-slate-600 font-light">Weather Temp Markets</span>
          <div className="flex items-center gap-1.5">
            <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.5)]" />
            <span className="text-[11px] text-slate-500 font-light">Connected</span>
          </div>
        </div>
      </footer>
    </div>
  )
}

export default App
