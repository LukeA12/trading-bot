import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine
} from 'recharts'
import { motion } from 'framer-motion'
import type { EquityPoint } from '../types'

interface Props {
  data: EquityPoint[]
  initialBankroll: number
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload || !payload.length) return null
  const value = payload[0].value
  const isPositive = value >= 0

  return (
    <div className="bg-[#111a2e]/95 border border-indigo-500/20 px-3 py-2 rounded-lg backdrop-blur-sm shadow-lg">
      <p className="text-[11px] text-slate-400 mb-0.5 font-light">{label}</p>
      <p className={`text-sm font-semibold tabular-nums ${isPositive ? 'text-emerald-400' : 'text-rose-400'}`}>
        {isPositive ? '+' : ''}${value.toFixed(2)}
      </p>
    </div>
  )
}

export function EquityChart({ data, initialBankroll }: Props) {
  if (data.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-slate-500">
        <p className="text-xs">No trade history</p>
        <p className="text-[11px] mt-1 text-slate-600 font-light">Chart appears after settled trades</p>
      </div>
    )
  }

  const chartData = [
    { timestamp: 'Start', pnl: 0, bankroll: initialBankroll },
    ...data.map(d => ({
      ...d,
      timestamp: new Date(d.timestamp).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    }))
  ]

  const currentPnl = data.length > 0 ? data[data.length - 1].pnl : 0
  const isPositive = currentPnl >= 0
  const minPnl = Math.min(0, ...data.map(d => d.pnl))
  const maxPnl = Math.max(0, ...data.map(d => d.pnl))
  const padding = Math.max(Math.abs(minPnl), Math.abs(maxPnl)) * 0.2

  const gradientId = `equityGradient-${isPositive ? 'green' : 'red'}`

  return (
    <motion.div
      className="h-full"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.5 }}
    >
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={chartData} margin={{ top: 5, right: 5, left: -15, bottom: 0 }}>
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop
                offset="5%"
                stopColor={isPositive ? '#34d399' : '#f43f5e'}
                stopOpacity={0.3}
              />
              <stop
                offset="95%"
                stopColor={isPositive ? '#34d399' : '#f43f5e'}
                stopOpacity={0}
              />
            </linearGradient>
          </defs>

          <CartesianGrid strokeDasharray="3 3" stroke="rgba(99,102,241,0.06)" vertical={false} />

          <XAxis
            dataKey="timestamp"
            stroke="#475569"
            fontSize={10}
            tickLine={false}
            axisLine={false}
            dy={5}
            fontFamily="IBM Plex Mono"
          />

          <YAxis
            stroke="#475569"
            fontSize={10}
            tickLine={false}
            axisLine={false}
            tickFormatter={(value) => `$${value}`}
            domain={[minPnl - padding, maxPnl + padding]}
            dx={-5}
            fontFamily="IBM Plex Mono"
          />

          <Tooltip content={<CustomTooltip />} />

          <ReferenceLine y={0} stroke="rgba(99,102,241,0.15)" strokeDasharray="3 3" />

          <Area
            type="monotone"
            dataKey="pnl"
            stroke={isPositive ? '#34d399' : '#f43f5e'}
            strokeWidth={2}
            fill={`url(#${gradientId})`}
            animationDuration={800}
          />
        </AreaChart>
      </ResponsiveContainer>
    </motion.div>
  )
}
