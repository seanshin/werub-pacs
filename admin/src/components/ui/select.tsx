"use client"

import * as React from "react"

interface SelectContextValue {
  value: string
  onValueChange: (value: string) => void
}

const SelectContext = React.createContext<SelectContextValue>({ value: "", onValueChange: () => {} })

function Select({ children, value = "", onValueChange }: { children: React.ReactNode; value?: string; onValueChange?: (value: string) => void }) {
  const [internalValue, setInternalValue] = React.useState(value)
  const currentValue = onValueChange ? value : internalValue
  const handleChange = onValueChange ?? setInternalValue
  return <SelectContext.Provider value={{ value: currentValue, onValueChange: handleChange }}>{children}</SelectContext.Provider>
}

function SelectTrigger({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`flex h-10 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 ${className}`}>
      {children}
    </div>
  )
}

function SelectValue({ placeholder = "" }: { placeholder?: string }) {
  const { value } = React.useContext(SelectContext)
  return <span>{value || placeholder}</span>
}

function SelectContent({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`relative z-50 min-w-[8rem] overflow-hidden rounded-md border bg-popover text-popover-foreground shadow-md ${className}`}>
      {children}
    </div>
  )
}

function SelectItem({ children, value, className = "" }: { children: React.ReactNode; value: string; className?: string }) {
  const { value: selectedValue, onValueChange } = React.useContext(SelectContext)
  return (
    <div
      className={`relative flex w-full cursor-pointer select-none items-center rounded-sm py-1.5 px-2 text-sm outline-none hover:bg-accent ${selectedValue === value ? "bg-accent" : ""} ${className}`}
      onClick={() => onValueChange(value)}
    >
      {children}
    </div>
  )
}

export { Select, SelectTrigger, SelectValue, SelectContent, SelectItem }
