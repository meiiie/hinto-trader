/**
 * Liquidity Zone Plugin for Lightweight Charts
 *
 * Renders Supply/Demand zones (Stop Loss Clusters & TP Zones) directly on the chart canvas.
 *
 * Visualization:
 * - Red Tint Zones: Supply / Resistance (TP Zones)
 * - Green Tint Zones: Demand / Support (SL Clusters / Buy Zones)
 * - Zones extend horizontally across the chart.
 */

import {
    ISeriesPrimitive,
    IPrimitivePaneRenderer,
    IPrimitivePaneView,
    SeriesAttachedParameter,
    Time
} from 'lightweight-charts';

export interface ZoneData {
    priceHigh: number;
    priceLow: number;
    type: 'supply' | 'demand'; // supply = red, demand = green
    strength: number; // 0-1 opacity multiplier
}

interface LiquidityZonePluginOptions {
    demandColor: string; // e.g. 'rgba(0, 150, 136, 0.15)'
    supplyColor: string; // e.g. 'rgba(255, 82, 82, 0.15)'
}

class LiquidityZonePaneRenderer implements IPrimitivePaneRenderer {
    private _data: ZoneData[];
    private _options: LiquidityZonePluginOptions;
    private _chart: SeriesAttachedParameter<Time> | null = null;

    constructor(
        data: ZoneData[],
        options: LiquidityZonePluginOptions,
        chart: SeriesAttachedParameter<Time> | null
    ) {
        this._data = data;
        this._options = options;
        this._chart = chart;
    }

    draw(target: { useBitmapCoordinateSpace: (callback: (scope: { context: CanvasRenderingContext2D; bitmapSize: { width: number; height: number }; horizontalPixelRatio: number; verticalPixelRatio: number }) => void) => void }): void {
        if (!this._chart || this._data.length === 0) return;

        const series = this._chart.series;
        const data = this._data;

        target.useBitmapCoordinateSpace((scope) => {
            const ctx = scope.context;
            const { width, height } = scope.bitmapSize; // Physical pixels
            const { verticalPixelRatio } = scope;

            ctx.save();

            for (const zone of data) {
                // Convert prices to coordinates using series (not priceScale)
                const yHigh = series.priceToCoordinate(zone.priceHigh);
                const yLow = series.priceToCoordinate(zone.priceLow);

                if (yHigh === null || yLow === null) continue;

                // Scale to bitmap coordinates
                const scaledYHigh = yHigh * verticalPixelRatio;
                const scaledYLow = yLow * verticalPixelRatio;
                const scaledHeight = scaledYLow - scaledYHigh; // yLow is numerically larger (lower on screen)

                // Skip if zone is outside view or too small
                if (scaledYLow < 0 || scaledYHigh > height || Math.abs(scaledHeight) < 1) continue;

                // Set color based on type
                ctx.fillStyle = zone.type === 'demand'
                    ? this._options.demandColor
                    : this._options.supplyColor;

                // Adjust opacity by strength if needed (advanced)
                // ctx.globalAlpha = zone.strength;

                // Draw rectangle full width
                ctx.fillRect(0, scaledYHigh, width, scaledHeight);
            }

            ctx.restore();
        });
    }
}

class LiquidityZonePaneView implements IPrimitivePaneView {
    private _source: LiquidityZonePlugin;

    constructor(source: LiquidityZonePlugin) {
        this._source = source;
    }

    renderer(): IPrimitivePaneRenderer | null {
        return new LiquidityZonePaneRenderer(
            this._source.getData(),
            this._source.getOptions(),
            this._source.getChart()
        );
    }

    zOrder(): 'bottom' | 'normal' | 'top' {
        return 'bottom'; // Behind candles
    }
}

export class LiquidityZonePlugin implements ISeriesPrimitive<Time> {
    private _paneView: LiquidityZonePaneView;
    private _data: ZoneData[] = [];
    private _options: LiquidityZonePluginOptions;
    private _chart: SeriesAttachedParameter<Time> | null = null;
    private _requestUpdate?: () => void;

    constructor(options: Partial<LiquidityZonePluginOptions> = {}) {
        this._options = {
            demandColor: options.demandColor || 'rgba(0, 150, 136, 0.15)', // Green tint
            supplyColor: options.supplyColor || 'rgba(255, 82, 82, 0.15)', // Red tint
        };
        this._paneView = new LiquidityZonePaneView(this);
    }

    attached(param: SeriesAttachedParameter<Time>): void {
        this._chart = param;
        this._requestUpdate = param.requestUpdate;
    }

    detached(): void {
        this._chart = null;
        this._requestUpdate = undefined;
    }

    paneViews(): readonly IPrimitivePaneView[] {
        return [this._paneView];
    }

    setData(data: ZoneData[]): void {
        this._data = data;
        if (this._requestUpdate) {
            this._requestUpdate();
        }
    }

    // Getters
    getData(): ZoneData[] {
        return this._data;
    }

    getOptions(): LiquidityZonePluginOptions {
        return this._options;
    }

    getChart(): SeriesAttachedParameter<Time> | null {
        return this._chart;
    }
}
