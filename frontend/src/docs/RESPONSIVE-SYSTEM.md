# Responsive System Documentation

## Overview

Hệ thống Adaptive UI cho phép ứng dụng Hinto Pro hoạt động tối ưu trên cả Desktop và Android từ single codebase. Áp dụng Binance UI Refined 2025 patterns và Material Design 3 Expressive.

## Breakpoint System

### Breakpoints

| Device | Width Range | DeviceType |
|--------|-------------|------------|
| Mobile | 0 - 767px | `mobile` |
| Tablet | 768 - 1023px | `tablet` |
| Desktop | 1024 - 1439px | `desktop` |
| Wide | 1440px+ | `desktop` |

### Usage

```tsx
import { useBreakpoint } from '../hooks/useBreakpoint';

const MyComponent = () => {
  const { isMobile, isTablet, isDesktop, responsive } = useBreakpoint();

  return (
    <div style={{
      padding: responsive(12, 16, 24), // mobile, tablet, desktop
      fontSize: responsive(14, 13, 12),
    }}>
      {isMobile ? <MobileView /> : <DesktopView />}
    </div>
  );
};
```

### responsive() Utility

Fallback chain: `desktop → tablet → mobile`

```tsx
// If on desktop and desktop value not provided, falls back to tablet, then mobile
responsive(mobileValue, tabletValue?, desktopValue?)
```

## Layout System

### AdaptiveLayout

Automatically switches between layouts based on breakpoint:

```tsx
import { AdaptiveLayout } from '../layouts/AdaptiveLayout';

<AdaptiveLayout activeTab={activeTab} onTabChange={setActiveTab}>
  {children}
</AdaptiveLayout>
```

### Layout Components

| Layout | Device | Features |
|--------|--------|----------|
| MobileLayout | Mobile | Single column, bottom nav, safe area |
| TabletLayout | Tablet | 2-column, collapsible panel |
| DesktopLayout | Desktop | 3-column, sidebar + chart + panel |

## Responsive Components

### ResponsiveButton

Touch-optimized button with minimum 44px touch target on mobile.

```tsx
import { ResponsiveButton } from '../components/common';

<ResponsiveButton
  variant="primary" // primary | secondary | danger
  size="md"         // sm | md | lg
  fullWidth={false}
>
  Click Me
</ResponsiveButton>
```

### ResponsiveInput

Touch-optimized input with minimum 48px height on mobile.

```tsx
import { ResponsiveInput } from '../components/common';

<ResponsiveInput
  type="text"
  placeholder="Enter value"
  prefix={<Icon />}
  suffix={<Icon />}
/>
```

### BottomSheet

Slide-up panel for mobile with snap points and drag gestures.

```tsx
import { BottomSheet } from '../components/common';

<BottomSheet
  isOpen={isOpen}
  onClose={() => setIsOpen(false)}
  snapPoints={['half', 'full']} // peek | half | full
  title="Order Form"
>
  {content}
</BottomSheet>
```

## Hooks

### useBreakpoint

Access breakpoint state and responsive utility.

```tsx
const {
  isMobile,    // boolean
  isTablet,    // boolean
  isDesktop,   // boolean
  width,       // number
  height,      // number
  deviceType,  // 'mobile' | 'tablet' | 'desktop'
  isTouch,     // boolean
  platform,    // 'android' | 'ios' | 'desktop'
  responsive,  // <T>(mobile: T, tablet?: T, desktop?: T) => T
} = useBreakpoint();
```

### useDeviceType

Detect touch capability and platform.

```tsx
const { isTouch, platform } = useDeviceType();
```

### useSafeArea

Get safe area insets for notch/navigation bar.

```tsx
const { top, right, bottom, left } = useSafeArea();
```

### useScrollPosition

Preserve scroll position per tab.

```tsx
import { useTabScrollPosition } from '../hooks/useScrollPosition';

const containerRef = useRef<HTMLElement>(null);
useTabScrollPosition(activeTab, containerRef);
```

## Theme Tokens

### Responsive Spacing

```tsx
THEME.responsive.spacing.mobile  // { xs: 4, sm: 8, md: 12, lg: 16, xl: 20 }
THEME.responsive.spacing.tablet  // { xs: 4, sm: 8, md: 14, lg: 18, xl: 24 }
THEME.responsive.spacing.desktop // { xs: 4, sm: 8, md: 16, lg: 20, xl: 28 }
```

### Touch Targets

```tsx
THEME.responsive.touchTarget.mobile  // 44px (minimum)
THEME.responsive.touchTarget.desktop // 32px
```

### Typography

```tsx
THEME.responsive.typography.mobile.base  // 14px
THEME.responsive.typography.desktop.base // 12px
```

## Performance Optimizations

### Lazy Loading

Layouts are lazy-loaded using `React.lazy()`:

```tsx
const MobileLayout = lazy(() => import('./MobileLayout'));
const TabletLayout = lazy(() => import('./TabletLayout'));
const DesktopLayout = lazy(() => import('./DesktopLayout'));
```

### GPU-Accelerated Animations

- Use `transform` and `opacity` instead of layout properties
- Use `will-change` sparingly
- Respect `prefers-reduced-motion`

```tsx
const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const transitionDuration = prefersReducedMotion ? '0.1s' : '0.3s';
```

### Scroll Position Preservation

Scroll positions are preserved per tab using `useTabScrollPosition`:

```tsx
useTabScrollPosition(activeTab, containerRef);
```

## Best Practices

1. **Always use `responsive()` for values that differ by device**
2. **Ensure touch targets are at least 44px on mobile**
3. **Use `useSafeArea()` for layouts with notch/navigation bar**
4. **Prefer `transform`/`opacity` for animations**
5. **Test on actual devices, not just browser resize**

## File Structure

```
src/
├── providers/
│   └── BreakpointProvider.tsx
├── hooks/
│   ├── useBreakpoint.ts
│   ├── useDeviceType.ts
│   ├── useSafeArea.ts
│   └── useScrollPosition.ts
├── layouts/
│   ├── AdaptiveLayout.tsx
│   ├── MobileLayout.tsx
│   ├── TabletLayout.tsx
│   └── DesktopLayout.tsx
├── components/
│   ├── navigation/
│   │   ├── BottomNavigation.tsx
│   │   ├── MobileHeader.tsx
│   │   └── HeaderNavigation.tsx
│   ├── common/
│   │   ├── ResponsiveButton.tsx
│   │   ├── ResponsiveInput.tsx
│   │   └── BottomSheet.tsx
│   └── trading/
│       ├── ChartContainer.tsx
│       ├── PortfolioMobile.tsx
│       └── OrderPanelMobile.tsx
└── styles/
    ├── breakpoints.ts
    └── theme.ts
```
