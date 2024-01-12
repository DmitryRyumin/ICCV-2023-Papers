# show_file_content.sh

show_file_content() {
  local file_path=$1
  local display_file_contents=$2

  if [[ -f "$file_path" ]]; then
    if [[ "$display_file_contents" == 'true' ]]; then
      echo "Displaying content of the file:"
      cat "$file_path"
    else
      echo "Displaying content is blocked."
    fi
  else
    echo "File does not exist."
  fi
}