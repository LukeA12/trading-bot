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
import { useState } from 'react'
import type { EquityPoint } from '../types'

interface Props {
  data: EquityPoint[]
  initialBankroll: number
  equityByStrategy?: Record<string, EquityPoint[]>
}

const STRATEGY_TABS = [
  { id: 'all', label: 'All', color: '#818cf8' },
  { id: '1', label: 'S1', color: '#94a3b8' },
  { id: '2', label: 'S2', color: '#60a5fa' },
  { id: '3', label: 'S3', color: '#a78bfa' },
]

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

export function EquityChart({ data, initialBankroll, equityByStrategy = {} }: Props) {
  const [activeTab, setActiveTab] = useState('all')

  const activeData = activeTab === 'all' ? data : (equityByStrategy[activeTab] || [])

  if (activeData.length === 0) {
    return (
      <div className="h-full flex flex-col">
        <div className="flex gap-1 mb-2">
          {STRATEGY_TABS.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`text-[10px] px-2 py-0.5 rounded transition-colors ${
                activeTab === tab.id
                  ? 'bg-indigo-500/20 text-indigo-300 font-medium'
                  : 'text-slate-500 hover:text-slate-400'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <div className="flex-1 flex flex-col items-center justify-center text-slate-500">
          <p className="text-xs">No trade history</p>
          <p className="text-[11px] mt-1 text-slate-600 font-light">
            {activeTab === 'all' ? 'Chart appears after settled trades' : `No Strategy ${activeTab} trades settled yet`}
          </p>
        </div>
      </div>
    )
  }

  const chartData = [
    { timestamp: 'Start', pnl: 0, bankroll: initialBankroll },
    ...activeData.map(d => ({
      ...d,
      timestamp: new Date(d.timestamp).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    }))
  ]

  const currentPnl = activeData.length > 0 ? activeData[activeData.length - 1].pnl : 0
  const isPositive = currentPnl >= 0
  const minPnl = Math.min(0, ...activeData.map(d => d.pnl))
  const maxPnl = Math.max(0, ...activeData.map(d => d.pnl))
  const padding = Math.max(Math.abs(minPnl), Math.abs(maxPnl)) * 0.2

  const gradientId = `equityGradient-${activeTab}-${isPositive ? 'green' : 'red'}`

  return (
    <motion.div
      className="h-full flex flex-col"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.5 }}
    >
      <div className="flex gap-1 mb-2">
        {STRATEGY_TABS.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`text-[10px] px-2 py-0.5 rounded transition-colors ${
              activeTab === tab.id
                ? 'bg-indigo-500/20 text-indigo-300 font-medium'
                : 'text-slate-500 hover:text-slate-400'
            }`}
          >
            {tab.label}
          </button>
        ))}
        <span className={`ml-auto text-[10px] tabular-nums font-medium ${isPositive ? 'text-emerald-400' : 'text-rose-400'}`}>
          {isPositive ? '+' : ''}${currentPnl.toFixed(0)}
        </span>
      </div>
      <div className="flex-1">
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
      </div>
    </motion.div>
  )
}
