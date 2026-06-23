import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center rounded border px-2 py-0.5 text-xs font-medium transition-colors',
  {
    variants: {
      variant: {
        default:  'border-zinc-700 bg-zinc-800 text-zinc-300',
        pending:  'border-amber-400/30 bg-amber-400/10 text-amber-400',
        active:   'border-blue-400/30 bg-blue-400/10 text-blue-400',
        success:  'border-emerald-400/30 bg-emerald-400/10 text-emerald-400',
        muted:    'border-zinc-700 bg-zinc-900 text-zinc-500',
        danger:   'border-red-400/30 bg-red-400/10 text-red-400',
        warning:  'border-orange-400/30 bg-orange-400/10 text-orange-400',
      },
    },
    defaultVariants: { variant: 'default' },
  },
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />
}

export { Badge, badgeVariants }
