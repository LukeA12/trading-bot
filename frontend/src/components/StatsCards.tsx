import { motion } from 'framer-motion'
import type { BotStats } from '../types'

interface Props {
  stats: BotStats
}

export function StatsCards({ stats }: Props) {
  const winRate = stats.total_trades > 0 ? (stats.winning_trades / stats.total_trades * 100) : 0
  const returnPercent = stats.bankroll - stats.total_pnl > 0
    ? ((stats.total_pnl / (stats.bankroll - stats.total_pnl)) * 100)
    : 0

  return (
    <div className="flex items-center gap-4">
      <motion.div className="flex items-center gap-2 px-3 py-1 rounded-lg bg-slate-800/40 border border-indigo-500/10" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
        <span className="text-[11px] text-slate-500 font-light">Bank</span>
        <span className="text-sm font-semibold tabular-nums text-slate-100">
          ${stats.bankroll >= 1000 ? (stats.bankroll / 1000).toFixed(1) + 'K' : stats.bankroll.toFixed(0)}
        </span>
      </motion.div>

      <motion.div className="flex items-center gap-2 px-3 py-1 rounded-lg bg-slate-800/40 border border-indigo-500/10" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.05 }}>
        <span className="text-[11px] text-slate-500 font-light">P&L</span>
        <span className={`text-sm font-semibold tabular-nums ${stats.total_pnl >= 0 ? 'text-emerald-400 glow-green' : 'text-rose-400 glow-red'}`}>
          {stats.total_pnl >= 0 ? '+' : ''}${Math.abs(stats.total_pnl).toFixed(0)}
        </span>
        <span className={`text-[10px] tabular-nums ${returnPercent >= 0 ? 'text-emerald-400/60' : 'text-rose-400/60'}`}>
          {returnPercent >= 0 ? '+' : ''}{returnPercent.toFixed(1)}%
        </span>
      </motion.div>

      <motion.div className="flex items-center gap-2 px-3 py-1 rounded-lg bg-slate-800/40 border border-indigo-500/10" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.1 }}>
        <span className="text-[11px] text-slate-500 font-light">Win</span>
        <span className={`text-sm font-semibold tabular-nums ${winRate >= 55 ? 'text-emerald-400' : winRate >= 45 ? 'text-amber-400' : 'text-rose-400'}`}>
          {winRate.toFixed(0)}%
        </span>
        <span className="text-[10px] text-slate-500 tabular-nums font-light">
          {stats.winning_trades}/{stats.total_trades}
        </span>
      </motion.div>

      <motion.div className="flex items-center gap-2 px-3 py-1 rounded-lg bg-slate-800/40 border border-indigo-500/10" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.15 }}>
        <span className="text-[11px] text-slate-500 font-light">Trades</span>
        <span className="text-sm font-semibold tabular-nums text-slate-100">{stats.total_trades}</span>
        {stats.is_running && <div className="live-dot" />}
      </motion.div>
    </div>
  )
}
