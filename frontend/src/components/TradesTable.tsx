import { ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react'
import { useState, useMemo } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import type { Trade } from '../types'
import { platformStyles } from '../utils'

interface Props {
  trades: Trade[]
}

type SortKey = 'timestamp' | 'size' | 'pnl' | 'result'
type SortDir = 'asc' | 'desc'

export function TradesTable({ trades }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>('timestamp')
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  const sortedTrades = useMemo(() => {
    return [...trades].sort((a, b) => {
      let aVal: number | string, bVal: number | string
      switch (sortKey) {
        case 'timestamp':
          aVal = new Date(a.timestamp).getTime()
          bVal = new Date(b.timestamp).getTime()
          break
        case 'size':
          aVal = a.size; bVal = b.size; break
        case 'pnl':
          aVal = a.pnl ?? 0; bVal = b.pnl ?? 0; break
        case 'result':
          aVal = a.result; bVal = b.result; break
        default: return 0
      }
      if (typeof aVal === 'string') {
        return sortDir === 'asc'
          ? aVal.localeCompare(bVal as string)
          : (bVal as string).localeCompare(aVal)
      }
      return sortDir === 'asc' ? aVal - (bVal as number) : (bVal as number) - aVal
    })
  }, [trades, sortKey, sortDir])

  const SortIcon = ({ column }: { column: SortKey }) => {
    if (sortKey !== column) return <ArrowUpDown className="w-2.5 h-2.5 text-slate-600" />
    return sortDir === 'asc'
      ? <ArrowUp className="w-2.5 h-2.5 text-indigo-400" />
      : <ArrowDown className="w-2.5 h-2.5 text-indigo-400" />
  }

  if (trades.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-8 text-slate-500">
        <p className="text-xs">No trades yet</p>
        <p className="text-[11px] mt-1 font-light">Trades will appear here</p>
      </div>
    )
  }

  return (
    <table className="w-full">
      <thead className="sticky top-0 bg-[#0f172a] z-10">
        <tr className="text-slate-500 text-left text-[11px] border-b border-indigo-500/10">
          <th className="py-1.5 px-1.5 font-medium w-5"></th>
          <th
            className="py-1.5 px-1.5 font-medium cursor-pointer hover:text-slate-300 transition-colors"
            onClick={() => handleSort('result')}
          >
            <div className="flex items-center gap-0.5">
              St <SortIcon column="result" />
            </div>
          </th>
          <th className="py-1.5 px-1.5 font-medium">Str</th>
          <th className="py-1.5 px-1.5 font-medium">Market</th>
          <th className="py-1.5 px-1.5 font-medium text-center">Dir</th>
          <th className="py-1.5 px-1.5 font-medium text-right">Entry</th>
          <th className="py-1.5 px-1.5 font-medium text-right">Edge</th>
          <th className="py-1.5 px-1.5 font-medium text-right">Model</th>
          <th className="py-1.5 px-1.5 font-medium text-right">Mkt</th>
          <th
            className="py-1.5 px-1.5 font-medium text-right cursor-pointer hover:text-slate-300 transition-colors"
            onClick={() => handleSort('size')}
          >
            <div className="flex items-center justify-end gap-0.5">
              Size <SortIcon column="size" />
            </div>
          </th>
          <th
            className="py-1.5 px-1.5 font-medium text-right cursor-pointer hover:text-slate-300 transition-colors"
            onClick={() => handleSort('pnl')}
          >
            <div className="flex items-center justify-end gap-0.5">
              P&L <SortIcon column="pnl" />
            </div>
          </th>
          <th
            className="py-1.5 px-1.5 font-medium text-right cursor-pointer hover:text-slate-300 transition-colors"
            onClick={() => handleSort('timestamp')}
          >
            <div className="flex items-center justify-end gap-0.5">
              Time <SortIcon column="timestamp" />
            </div>
          </th>
        </tr>
      </thead>
      <tbody>
        <AnimatePresence>
          {sortedTrades.map((trade, i) => {
            const isPending = trade.result === 'pending'
            const isWin = trade.result === 'win'
            const isUp = trade.direction === 'up'
            const style = platformStyles[trade.platform?.toLowerCase()]

            return (
              <motion.tr
                key={trade.id}
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.02 }}
                className="border-b border-indigo-500/[0.06] hover:bg-indigo-500/[0.04] text-[11px] transition-colors"
              >
                <td className="py-1 px-1.5">
                  {style && (
                    <span className={`platform-badge ${style.badge}`}>
                      {style.icon}
                    </span>
                  )}
                </td>
                <td className="py-1 px-1.5">
                  <span className={`text-[10px] font-medium rounded-full px-1.5 py-0.5 ${
                    isPending ? 'text-amber-400 bg-amber-400/10' : isWin ? 'text-emerald-400 bg-emerald-400/10' : 'text-rose-400 bg-rose-400/10'
                  }`}>
                    {isPending ? 'Pnd' : isWin ? 'Win' : 'Loss'}
                  </span>
                </td>
                <td className="py-1 px-1.5">
                  <span className={`text-[10px] font-semibold rounded px-1 py-0.5 ${
                    trade.strategy === 3 ? 'text-purple-400 bg-purple-400/10' :
                    trade.strategy === 2 ? 'text-blue-400 bg-blue-400/10' :
                    'text-slate-400 bg-slate-400/10'
                  }`}>
                    S{trade.strategy || 1}
                  </span>
                </td>
                <td className="py-1 px-1.5">
                  <span className="text-slate-400 truncate block max-w-[90px]" title={trade.event_slug || trade.market_ticker}>
                    {(trade.event_slug || trade.market_ticker).replace('btc-updown-5m-', '')}
                  </span>
                </td>
                <td className="py-1 px-1.5 text-center">
                  <span className={`text-[10px] font-semibold ${isUp || trade.direction === 'yes' ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {trade.direction}
                  </span>
                </td>
                <td className="py-1 px-1.5 text-right text-slate-300 tabular-nums">
                  {(trade.entry_price * 100).toFixed(0)}¢
                </td>
                <td className="py-1 px-1.5 text-right">
                  {trade.edge_at_entry != null ? (
                    <span className={`tabular-nums ${Math.abs(trade.edge_at_entry) >= 0.15 ? 'text-purple-400' : 'text-slate-400'}`}>
                      {(trade.edge_at_entry * 100).toFixed(1)}%
                    </span>
                  ) : (
                    <span className="text-slate-600">-</span>
                  )}
                </td>
                <td className="py-1 px-1.5 text-right">
                  {trade.model_probability != null ? (
                    <span className="tabular-nums text-indigo-300">
                      {(trade.model_probability * 100).toFixed(0)}%
                    </span>
                  ) : (
                    <span className="text-slate-600">-</span>
                  )}
                </td>
                <td className="py-1 px-1.5 text-right">
                  {trade.market_price_at_entry != null ? (
                    <span className="tabular-nums text-slate-400">
                      {(trade.market_price_at_entry * 100).toFixed(0)}¢
                    </span>
                  ) : (
                    <span className="text-slate-600">-</span>
                  )}
                </td>
                <td className="py-1 px-1.5 text-right text-slate-300 tabular-nums">
                  ${trade.size.toFixed(0)}
                </td>
                <td className="py-1 px-1.5 text-right">
                  {trade.pnl !== null ? (
                    <span className={`font-semibold tabular-nums ${
                      trade.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'
                    }`}>
                      {trade.pnl >= 0 ? '+' : ''}${trade.pnl.toFixed(0)}
                    </span>
                  ) : (
                    <span className="text-slate-600">-</span>
                  )}
                </td>
                <td className="py-1 px-1.5 text-right text-[10px] text-slate-500 tabular-nums font-light whitespace-nowrap">
                  {(() => { const d = new Date(trade.timestamp.endsWith('Z') ? trade.timestamp : trade.timestamp + 'Z'); return (<><div>{d.toLocaleDateString('en-US', { timeZone: 'America/Chicago', month: 'short', day: 'numeric' })}</div><div>{d.toLocaleTimeString('en-US', { timeZone: 'America/Chicago', hour: 'numeric', minute: '2-digit', hour12: true })}</div></>); })()}
                </td>
              </motion.tr>
            )
          })}
        </AnimatePresence>
      </tbody>
    </table>
  )
}
