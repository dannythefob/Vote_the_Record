# Reviewing and verifying facts

Everything the research tools gather starts as **Unverified**. Only the project owner marks
items verified. This page explains how, step by step.

## Start the review page

1. In VS Code, open a terminal: menu **Terminal → New Terminal**.
2. Type this and press Enter:

   ```
   .venv\Scripts\python src\review\review.py
   ```

3. Your browser opens the review page. (If it doesn't, open http://127.0.0.1:8765 yourself.)
4. The first time, type your name in **Your name as reviewer** and click **Save name**. This
   is the name shown publicly next to "Verified". It is saved on your computer only.

## Verify an item

Each card is one fact, or one link between a record and a survey question.

1. Click **Open source ↗** and read the source. Does it say exactly what the card says?
2. Click **Open archived copy ↗**. Does the saved copy show the same thing?
3. If both match, click **✓ Mark verified**, then **OK** in the confirmation box.

The card turns green. Behind the scenes, the page changes only that item's three
verification lines and runs the checker. If the checker objects, the change is undone and
you see why.

For a **question link**, also decide whether you agree with the options it supports and the
"Why" reasoning. Verify it only if you do.

## If something is wrong

Don't verify it. Tell Claude which item (the code after the name, like `B-02`) and what
doesn't match, and it will be corrected or removed.

## Made a mistake?

Click **Undo** on a green card to set it back to Unverified.

## Some buttons are grey

A grey button means the item can't be verified yet, and the card says why (usually that no
archived copy exists). Ask Claude to fix that first.

## When you're done

1. Go back to the terminal and press **Ctrl + C** to stop the review page.
2. Tell Claude "check and commit my verifications". It will check, build, commit, and push.
3. Merge on GitHub as usual. Your verifications go live, with your name and the date.
