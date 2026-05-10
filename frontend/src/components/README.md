# Frontend Components

**Location:** `frontend/src/components/`
**Last Updated:** 2025-12-29

---

## Core Chart Components

### CandleChart.tsx (1300+ lines)
Main trading chart component using `lightweight-charts` library.

**Features:**
- Multi-symbol support via Zustand store
- Real-time WebSocket updates
- VWAP, Bollinger Bands overlays
- Vietnamese timezone display (T2 29 Thg 12 '25 17:00)
- Data deduplication to prevent duplicate timestamp errors
- Signal markers with tooltips


### BBFillPlugin.ts (250 lines)
Custom lightweight-charts plugin for filling area between BB bands.

**Why Custom Plugin?**
`lightweight-charts` AreaSeries only fills from line to chart bottom. To fill BETWEEN two lines (BB upper/lower), a custom plugin is required.

**Technical Approach:**
```
BB Upper ─────────────────────
    ▓▓▓▓▓▓ POLYGON FILL ▓▓▓▓▓▓  ← Custom canvas drawing
BB Lower ─────────────────────
```

**Usage:**
```typescript
import { BBFillPlugin } from './BBFillPlugin';

const bbFillPlugin = new BBFillPlugin({
    fillColor: 'rgba(31, 125, 200, 0.1)',
    upperSeries: bbUpperSeriesRef.current,
    lowerSeries: bbLowerSeriesRef.current,
});

candleSeries.attachPrimitive(bbFillPlugin);
bbFillPlugin.setDataFromArrays(bbUpperData, bbLowerData);
```

**API:**
- `setData(data: BBFillData[])` - Direct data array
- `setDataFromArrays(upper, lower)` - Build from separate arrays
- `setFillColor(color: string)` - Update fill color

---

## Color Scheme (BINANCE_COLORS)

| Element | Color | Notes |
|---------|-------|-------|
| Background | `#181A20` | Dark background |
| Buy | `#2EBD85` | Green |
| Sell | `#F6465D` | Red |
| VWAP | `#FB6C01` | Orange |
| BB Lines | `#1F7DC8` | Blue |
| BB Fill | `rgba(31,125,200,0.1)` | Translucent blue |

---

## Dependencies

- `lightweight-charts` v4+ (TradingView)
- React 19 with hooks
- Zustand for state management

---

Version: 1.0 | 2025-12-29
