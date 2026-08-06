"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  { href: "/runs", label: "Runs" },
  { href: "/", label: "Playground" },
] as const;

export function AppHeader() {
  const pathname = usePathname();

  return (
    <header className="site-header">
      <div className="site-header__inner">
        <Link className="site-brand" href="/" aria-label="SINAMA home">
          <Image
            src="/brand/sinama-logo-symbol.png"
            alt=""
            width={40}
            height={40}
            priority
          />
          <span>
            <strong>SINAMA</strong>
            <small>AI AGENT RELIABILITY LAB</small>
          </span>
        </Link>

        <nav className="site-nav" aria-label="Primary navigation">
          {NAV_ITEMS.map((item) => {
            const isActive =
              item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            return (
              <Link
                href={item.href}
                key={item.href}
                aria-current={isActive ? "page" : undefined}
                className={isActive ? "active" : undefined}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
