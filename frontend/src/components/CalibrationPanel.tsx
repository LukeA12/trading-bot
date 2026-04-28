import type { CalibrationSummary } from '../types'

interface Props {
  calibration: CalibrationSummary
}

export function CalibrationPanel({ calibration }: Props) {
  const accuracyPct = (calibration.accuracy * 100).toFixed(0)
  const accuracyColor = calibration.accuracy >= 0.55 ? '#34d399' : calibration.accuracy < 0.50 ? '#f43f5e' : '#94a3b8'

  const brierLabel = calibration.brier_score <= 0.20 ? 'Good' : calibration.brier_score <= 0.25 ? 'OK' : 'Poor'
  const brierColor = calibration.brier_score <= 0.20 ? '#34d399' : calibration.brier_score <= 0.25 ? '#f59e0b' : '#f43f5e'

  const predEdge = (calibration.avg_predicted_edge * 100).toFixed(1)
  const actualEdge = (calibration.avg_actual_edge * 100).toFixed(1)

  return (
    <div className="space-y-2">
      {/* Accuracy - large display */}
      <div className="flex items-center gap-3">
        <div className="text-2xl font-bold tabular-nums" style={{ color: accuracyColor }}>
          {accuracyPct}%
        </div>
        <div className="text-[11px] text-slate-500 leading-tight font-light">
          <div>Accuracy</div>
          <div className="tabular-nums text-slate-600">
            {Math.round(calibration.accuracy * calibration.total_with_outcome)}/{calibration.total_with_outcome}
          </div>
        </div>
      </div>

      {/* Brier + Edge comparison */}
      <div className="flex items-center justify-between text-[11px]">
        <div>
          <span className="text-slate-500 font-light">Brier: </span>
          <span className="tabular-nums" style={{ color: brierColor }}>
            {calibration.brier_score.toFixed(3)} ({brierLabel})
          </span>
        </div>
      </div>

      {/* Predicted vs Actual edge bars */}
      <div className="space-y-1">
        <div className="flex items-center gap-2 text-[11px]">
          <span className="text-slate-500 w-10 shrink-0 font-light">Pred</span>
          <div className="flex-1 meter-bar">
            <div
              className="meter-fill"
              style={{
                width: `${Math.min(100, Math.abs(calibration.avg_predicted_edge) * 500)}%`,
                backgroundColor: '#f59e0b'
              }}
            />
          </div>
          <span className="tabular-nums text-amber-400 w-10 text-right">{predEdge}%</span>
        </div>
        <div className="flex items-center gap-2 text-[11px]">
          <span className="text-slate-500 w-10 shrink-0 font-light">Actual</span>
          <div className="flex-1 meter-bar">
            <div
              className="meter-fill"
              style={{
                width: `${Math.min(100, Math.abs(calibration.avg_actual_edge) * 500)}%`,
                backgroundColor: calibration.avg_actual_edge >= 0 ? '#34d399' : '#f43f5e'
              }}
            />
          </div>
          <span
            className="tabular-nums w-10 text-right"
            style={{ color: calibration.avg_actual_edge >= 0 ? '#34d399' : '#f43f5e' }}
          >
            {actualEdge}%
          </span>
        </div>
      </div>

      <div className="text-[10px] text-slate-600 tabular-nums font-light">
        {calibration.total_signals} tracked / {calibration.total_with_outcome} settled
      </div>
    </div>
  )
}
