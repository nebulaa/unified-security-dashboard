"""Cloud security coverage (public coverage metrics) — X/Y coverage metrics for /executive.

Separate from `findings` on purpose. A finding answers "what is wrong with the
things we can see"; coverage answers "how many of the things that should be
protected actually are". Folding coverage into the findings pipeline would make
both dishonest, because a tool that stops reporting would silently shrink its
own denominator.
"""
