/**
 * BB Fill Plugin for Lightweight Charts
 *
 * Custom plugin that renders a filled area between two line series (BB Upper and Lower).
 * Uses the lightweight-charts plugin API to draw directly on canvas.
 *
 * SOTA Implementation based on lightweight-charts v4+ plugin architecture.
 */

import {
    ISeriesPrimitive,
    IPrimitivePaneRenderer,
    IPrimitivePaneView,
    SeriesAttachedParameter,
    Time,
    ISeriesApi
} from 'lightweight-charts';

interface BBFillData {
    time: Time;
    upperValue: number;
    lowerValue: number;
}

interface BBFillPluginOptions {
    fillColor: string;
    upperSeries: ISeriesApi<"Line">;
    lowerSeries: ISeriesApi<"Line">;
}

/**
 * Renderer that draws the filled polygon between BB upper and lower
 */
class BBFillPaneRenderer implements IPrimitivePaneRenderer {
    private _data: BBFillData[];
    private _fillColor: string;
    private _upperSeries: ISeriesApi<"Line">;
    private _lowerSeries: ISeriesApi<"Line">;
    private _chart: SeriesAttachedParameter<Time> | null = null;

    constructor(
        data: BBFillData[],
        fillColor: string,
        upperSeries: ISeriesApi<"Line">,
        lowerSeries: ISeriesApi<"Line">,
        chart: SeriesAttachedParameter<Time> | null
    ) {
        this._data = data;
        this._fillColor = fillColor;
        this._upperSeries = upperSeries;
        this._lowerSeries = lowerSeries;
        this._chart = chart;
    }

    draw(target: { useBitmapCoordinateSpace: (callback: (scope: { context: CanvasRenderingContext2D; bitmapSize: { width: number; height: number }; horizontalPixelRatio: number; verticalPixelRatio: number }) => void) => void }): void {
        if (!this._chart || this._data.length < 2) return;

        const timeScale = this._chart.chart.timeScale();
        const upperSeries = this._upperSeries;
        const lowerSeries = this._lowerSeries;
        const data = this._data;
        const fillColor = this._fillColor;

        target.useBitmapCoordinateSpace((scope) => {
            const ctx = scope.context;
            const { horizontalPixelRatio, verticalPixelRatio } = scope;

            ctx.save();
            ctx.beginPath();
            ctx.fillStyle = fillColor;

            // Draw upper line path (left to right)
            let firstPoint = true;
            for (const point of data) {
                const x = timeScale.timeToCoordinate(point.time);
                const yUpper = upperSeries.priceToCoordinate(point.upperValue);

                if (x === null || yUpper === null) continue;

                const scaledX = x * horizontalPixelRatio;
                const scaledYUpper = yUpper * verticalPixelRatio;

                if (firstPoint) {
                    ctx.moveTo(scaledX, scaledYUpper);
                    firstPoint = false;
                } else {
                    ctx.lineTo(scaledX, scaledYUpper);
                }
            }

            // Draw lower line path (right to left) to close the polygon
            for (let i = data.length - 1; i >= 0; i--) {
                const point = data[i];
                const x = timeScale.timeToCoordinate(point.time);
                const yLower = lowerSeries.priceToCoordinate(point.lowerValue);

                if (x === null || yLower === null) continue;

                const scaledX = x * horizontalPixelRatio;
                const scaledYLower = yLower * verticalPixelRatio;

                ctx.lineTo(scaledX, scaledYLower);
            }

            ctx.closePath();
            ctx.fill();
            ctx.restore();
        });
    }
}

/**
 * Pane view that creates the renderer
 */
class BBFillPaneView implements IPrimitivePaneView {
    private _source: BBFillPlugin;

    constructor(source: BBFillPlugin) {
        this._source = source;
    }

    renderer(): IPrimitivePaneRenderer | null {
        return new BBFillPaneRenderer(
            this._source.getData(),
            this._source.getFillColor(),
            this._source.getUpperSeries(),
            this._source.getLowerSeries(),
            this._source.getChart()
        );
    }

    zOrder(): 'bottom' | 'normal' | 'top' {
        return 'bottom';  // Draw behind candles
    }
}

/**
 * Main BB Fill Plugin class
 *
 * Usage:
 * ```typescript
 * const bbFillPlugin = new BBFillPlugin({
 *     fillColor: 'rgba(31, 125, 200, 0.1)',
 *     upperSeries: bbUpperSeriesRef.current,
 *     lowerSeries: bbLowerSeriesRef.current,
 * });
 * candleSeries.attachPrimitive(bbFillPlugin);
 * bbFillPlugin.setData(bbFillData);
 * ```
 */
export class BBFillPlugin implements ISeriesPrimitive<Time> {
    private _paneView: BBFillPaneView;
    private _data: BBFillData[] = [];
    private _fillColor: string;
    private _upperSeries: ISeriesApi<"Line">;
    private _lowerSeries: ISeriesApi<"Line">;
    private _chart: SeriesAttachedParameter<Time> | null = null;
    private _requestUpdate?: () => void;

    constructor(options: BBFillPluginOptions) {
        this._fillColor = options.fillColor;
        this._upperSeries = options.upperSeries;
        this._lowerSeries = options.lowerSeries;
        this._paneView = new BBFillPaneView(this);
    }

    // Called when plugin is attached to a series
    attached(param: SeriesAttachedParameter<Time>): void {
        this._chart = param;
        this._requestUpdate = param.requestUpdate;
    }

    // Called when plugin is detached
    detached(): void {
        this._chart = null;
        this._requestUpdate = undefined;
    }

    // Pane views for rendering
    paneViews(): readonly IPrimitivePaneView[] {
        return [this._paneView];
    }

    // Update the fill data
    setData(data: BBFillData[]): void {
        this._data = data;
        if (this._requestUpdate) {
            this._requestUpdate();
        }
    }

    // Build data from separate upper/lower arrays
    setDataFromArrays(
        upperData: Array<{ time: Time; value: number }>,
        lowerData: Array<{ time: Time; value: number }>
    ): void {
        // Create a map of lower values by time for efficient lookup
        const lowerMap = new Map<string, number>();
        for (const item of lowerData) {
            lowerMap.set(String(item.time), item.value);
        }

        // Build combined data
        const combinedData: BBFillData[] = [];
        for (const upper of upperData) {
            const timeKey = String(upper.time);
            const lowerValue = lowerMap.get(timeKey);
            if (lowerValue !== undefined) {
                combinedData.push({
                    time: upper.time,
                    upperValue: upper.value,
                    lowerValue: lowerValue,
                });
            }
        }

        this.setData(combinedData);
    }

    // Update fill color
    setFillColor(color: string): void {
        this._fillColor = color;
        if (this._requestUpdate) {
            this._requestUpdate();
        }
    }

    // Getters for internal use
    getData(): BBFillData[] {
        return this._data;
    }

    getFillColor(): string {
        return this._fillColor;
    }

    getUpperSeries(): ISeriesApi<"Line"> {
        return this._upperSeries;
    }

    getLowerSeries(): ISeriesApi<"Line"> {
        return this._lowerSeries;
    }

    getChart(): SeriesAttachedParameter<Time> | null {
        return this._chart;
    }
}

// Export types for external use
export type { BBFillData, BBFillPluginOptions };
