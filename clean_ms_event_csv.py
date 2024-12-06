import csv
import sys
# Define the log levels
log_levels = {"Critical", "Error", "Warning", "Information", "Verbose"}

def parse_messy_csv(file_path):
    cleaned_rows = []
    current_row = []

    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            stripped_line = line.strip()
            # Check if the line starts with any log level
            if any(stripped_line.startswith(level) for level in log_levels):
                # If there's an ongoing row, finalize it
                if current_row:
                    cleaned_rows.append(current_row)
                # Start a new row
                current_row = [stripped_line]
            else:
                # If the line doesn't start a new row, it belongs to the current one
                if current_row:
                    current_row[-1] += " " + stripped_line
                else:
                    current_row = [stripped_line]  # Handle cases with malformed data

        # Add the last row if present
        if current_row:
            cleaned_rows.append(current_row)

    # Split the concatenated rows by commas and clean them
    split_rows = [row[0].split(',', maxsplit=5) for row in cleaned_rows]
    return split_rows

def save_cleaned_csv(rows, output_file):
    with open(output_file, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["LogLevel", "DateTime", "Source", "EventID", "TaskCategory", "Description"])  # Header
        writer.writerows(rows)

if __name__ == "__main__":
    # input file is arg 1, eg 'all_events.csv'
    # output filename is arg 1 filename but with _cleaned in it, eg 'all_events_cleaned.csv'

    input_filename = sys.argv[1]
    output_filename = input_filename.replace('.csv', '_cleaned.csv')

    cleaned_data = parse_messy_csv(input_filename)
    save_cleaned_csv(cleaned_data, output_filename)
    print(f"Cleaned CSV saved to {output_filename}")
